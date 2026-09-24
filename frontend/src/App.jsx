import { useEffect, useRef, useState } from "react";
import Login from "./Login";
import { errorMessage } from "./errors";

const API_BASE = "/api";

// ---------------------------------------------------------------------------
// Token storage helpers
// ---------------------------------------------------------------------------
const TOKEN_KEY = "ai_kb_token";
const USER_KEY = "ai_kb_user";

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
function saveAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
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
  const messagesEndRef = useRef(null);

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

  function handleExpired() {
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
  }

  function handleLogin(newToken, newUser) {
    saveAuth(newToken, newUser);
    setToken(newToken);
    setUser(newUser);
    setConversationId(null);
    setMessages([
      {
        role: "assistant",
        content: `Welcome, ${newUser.full_name}! I can help you find information in your authorized company documents. What would you like to know?`,
        sources: [],
      },
    ]);
  }

  function handleLogout() {
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
          <button className="logout-btn" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

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
              <div className="message-content">{message.content}</div>
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
    </main>
  );
}
