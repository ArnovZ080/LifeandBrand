import { useState, FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
    } catch {
      setError("Invalid email or password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--color-bg)",
    }}>
      <div className="card" style={{ width: 380, padding: 36 }}>
        <div style={{ marginBottom: 28, textAlign: "center" }}>
          <div style={{ fontWeight: 700, fontSize: 20, marginBottom: 4 }}>Life & Brand</div>
          <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>Operations Platform</div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ marginBottom: 24 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              style={{ width: "100%" }}
            />
          </div>

          {error && (
            <div style={{
              background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 4,
              padding: "8px 12px", fontSize: 13, color: "#dc2626", marginBottom: 16,
            }}>
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} style={{ width: "100%", background: "#2563eb" }}>
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
