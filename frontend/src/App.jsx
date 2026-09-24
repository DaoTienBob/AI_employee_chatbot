import { useEffect, useRef, useState } from "react";
import Login from "./Login";
import Markdown from "./Markdown";
import Documents from "./Documents";
import { errorMessage } from "./errors";

const API_BASE = "/api";

// ---------------------------------------------------------------------------
// Token storage helpers
// ---------------------------------------------------------------------------
const TOKEN_KEY = "ai_kb_token";
const USER_KEY = "ai_kb_user";
// Epoch-ms at which the access token expires. Persisted so a page reload can
// still schedule a /auth/refresh *before* the token actually expires.
const TOKEN_EXPIRES_KEY = "ai_kb_token_expires_at";

// Refresh the session this long before expiry; retry gap for transient
// network failures while the token is still valid.
const REFRESH_BUFFER_MS = 60_000;
const REFRESH_RETRY_MS = 15_000;

function loadToken() {
  return localStorage.getItem(TOKEN_KEY) || null;
}
function loadUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY)) || null;
  } catch {
    return null;
  }
}
function saveAuth(token, user, expiresIn) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (expiresIn && expiresIn > 0) {
    localStorage.setItem(TOKEN_EXPIRES_KEY, String(Date.now() + expiresIn * 1000));
  }
}
function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(TOKEN_EXPIRES_KEY);
}

// Seconds until the persisted token expires, or null when unknown/absent.
function loadTokenTtlSeconds() {
  const raw = localStorage.getItem(TOKEN_EXPIRES_KEY);
  const expiresAt = raw ? Number(raw) : NaN;
  if (!Number.isFinite(expiresAt)) return null;
  return Math.max(0, (expiresAt - Date.now()) / 1000);
}

// ---------------------------------------------------------------------------
// Authenticated fetch helper — clears session on 401
// ---------------------------------------------------------------------------
async function apiFetch(path, options, onExpired) {
  const token = loadToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers || {}),
    },
  });
  if (res.status === 401) {
    clearAuth();
    onExpired?.();
    throw new Error("Session expired. Please sign in again.");
  }
  return res;
}

// ---------------------------------------------------------------------------
// Chat history loading — fetch the user's most recent conversation and return
// all of its messages so old history can be re-rendered after sign in.
// ---------------------------------------------------------------------------
async function fetchMostRecentConversation(onExpired) {
  const listRes = await apiFetch("/conversations", {}, onExpired);
  if (!listRes.ok) return null;
  const conversations = await listRes.json();
  if (!Array.isArray(conversations) || conversations.length === 0) return null;

  const conversationId = conversations[0].id; // newest first (backend ordering)
  const msgsRes = await apiFetch(`/conversations/${conversationId}`, {}, onExpired);
  if (!msgsRes.ok) return null;
  const history = await msgsRes.json();

  return {
    conversationId,
    messages: history.map((m) => ({
      role: m.role,
      content: m.content,
      sources: [],
    })),
  };
}

// ---------------------------------------------------------------------------
// Source references sub-component
// ---------------------------------------------------------------------------
function Sources({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;
  return (
    <div className="sources">
      <button
        className="sources-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? "▾" : "▸"} {sources.length} source
        {sources.length !== 1 ? "s" : ""}
      </button>
      {open && (
        <ul className="sources-list">
          {sources.map((s) => (
            <li key={s.chunk_id}>
              <strong>{s.document_name}</strong>
              {s.section ? ` — ${s.section}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Role badge
// ---------------------------------------------------------------------------
function RoleBadge({ role }) {
  return <span className={`role-badge role-${role}`}>{role}</span>;
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
export default function App() {
  const [backendStatus, setBackendStatus] = useState("Checking backend…");
  const [token, setToken] = useState(loadToken);
  const [user, setUser] = useState(loadUser);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Hello! Ask me anything about your company documents.",
      sources: [],
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [conversationId, setConversationId] = useState(null);
  // Lightweight page navigation: "chat" (default) or "documents" (admin page).
  const [view, setView] = useState("chat");
  const messagesEndRef = useRef(null);
  const refreshTimerRef = useRef(null);

  // Check backend health on mount
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((res) => res.json())
      .then((data) =>
        setBackendStatus(`Backend OK — ${data.app} v${data.version}`),
      )
      .catch(() =>
        setBackendStatus(
          "Backend unreachable — start FastAPI first (see README).",
        ),
      );
  }, []);

  // Auto-scroll to the latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load the user's most recent conversation history whenever they are
  // authenticated (on mount after a page refresh, and right after sign in).
  useEffect(() => {
    if (!token || !user) return;
    let cancelled = false;

    fetchMostRecentConversation(handleExpired)
      .then((history) => {
        if (cancelled) return;
        if (history) {
          setConversationId(history.conversationId);
          setMessages(history.messages);
        } else {
          setMessages([
            {
              role: "assistant",
              content: `Welcome, ${user.full_name}! I can help you find information in your authorized company documents. What would you like to know?`,
              sources: [],
            },
          ]);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([
            {
              role: "assistant",
              content: `Welcome, ${user.full_name}! I can help you find information in your authorized company documents. What would you like to know?`,
              sources: [],
            },
          ]);
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user]);

  // Every time a valid token is present, schedule a refresh covering both
  // fresh logins and page reloads (expires_at is persisted with the token).
  useEffect(() => {
    if (!token || !user) return;
    scheduleTokenRefresh(loadTokenTtlSeconds());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user]);

  // Clear any pending refresh timer when the app unmounts / session ends.
  useEffect(() => () => clearTokenRefreshTimer(), []);

  function handleExpired() {
    clearTokenRefreshTimer();
    setToken(null);
    setUser(null);
    setMessages([
      {
        role: "assistant",
        content: "Hello! Ask me anything about your company documents.",
        sources: [],
      },
    ]);
    setConversationId(null);
    setView("chat");
  }

  function clearTokenRefreshTimer() {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }

  // Refresh the session shortly before its token expires so long sessions do
  // not end with an abrupt 401 mid-chat. /auth/refresh re-checks is_active and
  // returns a fresh token, which is then rescheduled.
  async function refreshAccessToken() {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${loadToken()}` },
      });
      if (res.status === 401) {
        // Session really is gone (token expired / account deactivated).
        handleExpired();
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error("refresh failed");
      saveAuth(data.access_token, data.user, data.expires_in);
      setToken(data.access_token);
      setUser(data.user);
      scheduleTokenRefresh(data.expires_in);
    } catch {
      // Transient network error while the token is still valid: retry shortly
      // instead of logging the user out.
      clearTokenRefreshTimer();
      refreshTimerRef.current = setTimeout(refreshAccessToken, REFRESH_RETRY_MS);
    }
  }

  function scheduleTokenRefresh(expiresInSeconds) {
    clearTokenRefreshTimer();
    if (!expiresInSeconds || expiresInSeconds <= 0) return;
    const delayMs = Math.max(0, expiresInSeconds * 1000 - REFRESH_BUFFER_MS);
    refreshTimerRef.current = setTimeout(refreshAccessToken, delayMs);
  }

  function handleLogin(newToken, newUser, expiresIn) {
    saveAuth(newToken, newUser, expiresIn);
    setToken(newToken);
    setUser(newUser);
    setConversationId(null);
    scheduleTokenRefresh(expiresIn);
    // The authenticated-history effect below will load the user's most recent
    // conversation (or show a welcome message when they have no history yet).
    setMessages([]);
  }

  function handleLogout() {
    clearTokenRefreshTimer();
    clearAuth();
    setToken(null);
    setUser(null);
    setMessages([
      {
        role: "assistant",
        content: "Hello! Ask me anything about your company documents.",
        sources: [],
      },
    ]);
    setConversationId(null);
    setError("");
    setView("chat");
  }

  async function handleSend(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setError("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, sources: [] },
    ]);
    setLoading(true);

    try {
      const res = await apiFetch(
        "/chat",
        {
          method: "POST",
          body: JSON.stringify({
            question: text,
            conversation_id: conversationId,
          }),
        },
        handleExpired,
      );

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          errorMessage(data, res.status, `Server error (${res.status})`),
        );
      }

      const data = await res.json();
      setConversationId(data.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer,
          sources: data.sources || [],
          fallback: data.fallback,
        },
      ]);
    } catch (err) {
      setError(err.message || "Failed to send message. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  // Show login screen if not authenticated
  if (!token || !user) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <main className="app">
      <header className="app-header">
        <div className="app-header-left">
          <h1>AI Employee Knowledge Assistant</h1>
        </div>
        <div className="app-header-right">
          <p
            className={`status ${backendStatus.startsWith("Backend OK") ? "ok" : "warn"}`}
          >
            {backendStatus}
          </p>
          <span className="user-name">{user.full_name}</span>
          <RoleBadge role={user.role} />
          {user.is_admin && (
            <span className="role-badge role-admin">admin</span>
          )}
          {user.is_admin && (
            <button
              className="doc-manage-btn"
              onClick={() => setView(view === "documents" ? "chat" : "documents")}
              aria-pressed={view === "documents"}
            >
              {view === "documents" ? "← Back to chat" : "Manage documents"}
            </button>
          )}
          <button className="logout-btn" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      {view === "documents" && user.is_admin ? (
        <Documents onExpired={handleExpired} />
      ) : (
        <>
          {error && (
            <div className="error-bar" role="alert">
              {error}
              <button
                className="error-dismiss"
                onClick={() => setError("")}
                aria-label="Dismiss"
              >
                ✕
              </button>
            </div>
          )}

          <section className="chat">
            <div className="messages">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`message ${message.role}${message.fallback ? " fallback" : ""}`}
                >
                  <div className="message-content">
                    {message.role === "assistant" ? (
                      <Markdown content={message.content} />
                    ) : (
                      message.content
                    )}
                  </div>
                  {message.role === "assistant" && (
                    <Sources sources={message.sources} />
                  )}
                </div>
              ))}

              {loading && (
                <div className="message assistant">
                  <div className="typing-indicator">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            <form className="composer" onSubmit={handleSend}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question about internal documents…"
                aria-label="Question"
                disabled={loading}
              />
              <button type="submit" disabled={!input.trim() || loading}>
                {loading ? "…" : "Send"}
              </button>
            </form>
          </section>
        </>
      )}
    </main>
  );
}
