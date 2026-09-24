import { useState } from "react";
import { errorMessage } from "./errors";

const API_BASE = "/api";

/**
 * T19 — Login form.
 * Calls POST /api/auth/login and stores the token + user info via onLogin().
 */
export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          errorMessage(data, res.status, `Login failed (${res.status})`),
        );
      }
      const data = await res.json();
      onLogin(data.access_token, data.user, data.expires_in);
    } catch (err) {
      setError(err.message || "Network error — is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-wrapper">
      <div className="login-card">
        <h1>AI Employee Knowledge Assistant</h1>
        <p className="login-subtitle">Sign in with your company account</p>

        <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            required
            disabled={loading}
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            required
            disabled={loading}
          />

          {error && (
            <p className="login-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" disabled={loading || !email || !password}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {import.meta.env.DEV && (
          <p className="login-hint">
            Demo accounts: <code>employee@example.com</code>,{" "}
            <code>hr@example.com</code>, <code>manager@example.com</code> —
            password: <code>password123</code>.
            <br />
            Admin (for document management): <code>admin@example.com</code> — same password.
          </p>
        )}
      </div>
    </main>
  );
}
