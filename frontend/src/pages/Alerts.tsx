import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";

interface Contact {
  id: number;
  name: string;
  role: string | null;
  email: string | null;
  whatsapp_number: string | null;
  active_channels: string;
  departments_subscribed: string;
  quiet_hours_start: number;
  quiet_hours_end: number;
  is_active: boolean;
}

interface AlertHistory {
  id: number;
  batch_id: number;
  item_name: string;
  batch_reference: string | null;
  contact_name: string;
  alert_level: number;
  channel: string;
  status: string;
  message_preview: string | null;
  sent_at: string;
}

interface TriggerResult {
  alerts_sent: number;
  alerts_failed: number;
  alerts_suppressed: number;
  detail: Array<{ item: string; batch: string; contact: string; channel: string; status: string }>;
}

const DEPT_OPTIONS = ["bar", "kitchen", "floor", "general"];
const CHANNEL_OPTIONS = ["email", "teams", "whatsapp"];

const defaultForm = {
  name: "", role: "", email: "", whatsapp_number: "", teams_webhook_url: "",
  active_channels: "email", departments_subscribed: "kitchen,floor",
  quiet_hours_start: 22, quiet_hours_end: 7,
};

export default function Alerts() {
  const { orgUnitId: LOCATION_ID } = useAuth();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [triggerResult, setTriggerResult] = useState<TriggerResult | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const { data: contacts = [] } = useQuery<Contact[]>({
    queryKey: ["contacts", LOCATION_ID],
    queryFn: () => api.get(`/alerts/contacts?location_id=${LOCATION_ID}`).then(r => r.data),
  });

  const { data: history = [] } = useQuery<AlertHistory[]>({
    queryKey: ["alert-history", LOCATION_ID],
    queryFn: () => api.get(`/alerts/history?location_id=${LOCATION_ID}&days=7`).then(r => r.data),
    enabled: showHistory,
  });

  const createContact = useMutation({
    mutationFn: () => api.post("/alerts/contacts", { ...form, location_id: LOCATION_ID }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["contacts"] }); setShowForm(false); setForm(defaultForm); },
  });

  const deleteContact = useMutation({
    mutationFn: (id: number) => api.delete(`/alerts/contacts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["contacts"] }),
  });

  const triggerMutation = useMutation({
    mutationFn: () => api.post(`/alerts/trigger?location_id=${LOCATION_ID}`).then(r => r.data),
    onSuccess: (data) => { setTriggerResult(data); qc.invalidateQueries({ queryKey: ["alert-history"] }); },
  });

  const toggleChannel = (ch: string) => {
    const current = form.active_channels.split(",").filter(Boolean);
    const next = current.includes(ch) ? current.filter(x => x !== ch) : [...current, ch];
    setForm(f => ({ ...f, active_channels: next.join(",") }));
  };

  const toggleDept = (d: string) => {
    const current = form.departments_subscribed.split(",").filter(Boolean);
    const next = current.includes(d) ? current.filter(x => x !== d) : [...current, d];
    setForm(f => ({ ...f, departments_subscribed: next.join(",") }));
  };

  const levelLabel = (level: number) =>
    level === 0 ? "🚨 Urgent (today)" : level === 24 ? "🔴 Action (24h)" : "⚠️ Warning (48h)";

  const statusColor: Record<string, string> = { sent: "green", failed: "red", suppressed: "gray" };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Freshness Alerts</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            Managers receive expiry alerts via email, WhatsApp, or Teams — automatically deduped, quiet-hours aware.
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            className="secondary"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            {triggerMutation.isPending ? "Checking..." : "Run Alert Check Now"}
          </button>
          <button onClick={() => setShowForm(true)}>+ Add Manager</button>
        </div>
      </div>

      {/* Trigger result */}
      {triggerResult && (
        <div style={{
          background: triggerResult.alerts_failed > 0 ? "#fef3c7" : "#d1fae5",
          border: `1px solid ${triggerResult.alerts_failed > 0 ? "#f59e0b" : "#6ee7b7"}`,
          borderRadius: 8, padding: "12px 16px", marginBottom: 20,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            Alert check complete —{" "}
            {triggerResult.alerts_sent} sent · {triggerResult.alerts_failed} failed · {triggerResult.alerts_suppressed} suppressed
          </div>
          {triggerResult.detail.length > 0 && (
            <div style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
              {triggerResult.detail.map((d, i) => (
                <span key={i}>
                  <span className={`badge ${statusColor[d.status] ?? "gray"}`} style={{ marginRight: 6 }}>{d.status}</span>
                  {d.item} ({d.batch}) → {d.contact} via {d.channel}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
        {/* Contacts */}
        <div className="card">
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>Alert Recipients ({contacts.length})</h3>
          {contacts.length === 0 ? (
            <p style={{ color: "var(--color-text-muted)" }}>No managers added yet. Add one to start receiving alerts.</p>
          ) : contacts.map(c => (
            <div key={c.id} style={{
              padding: "12px 0", borderBottom: "1px solid var(--color-border)",
              display: "flex", justifyContent: "space-between", alignItems: "flex-start",
            }}>
              <div>
                <div style={{ fontWeight: 500 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>
                  {c.role && <span style={{ marginRight: 10 }}>{c.role}</span>}
                  {c.departments_subscribed.split(",").filter(Boolean).map(d => (
                    <span key={d} className="badge blue" style={{ marginRight: 4, fontSize: 10 }}>{d}</span>
                  ))}
                </div>
                <div style={{ fontSize: 12, marginTop: 4, display: "flex", gap: 6 }}>
                  {c.active_channels.split(",").filter(Boolean).map(ch => (
                    <span key={ch} className="badge gray" style={{ fontSize: 10 }}>{ch}</span>
                  ))}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                  Quiet: {c.quiet_hours_start}:00–{c.quiet_hours_end}:00
                </div>
              </div>
              <button
                className="secondary danger"
                style={{ fontSize: 11, padding: "3px 8px", background: "transparent", color: "var(--color-danger)", border: "1px solid var(--color-danger)" }}
                onClick={() => deleteContact.mutate(c.id)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>

        {/* Cron instructions */}
        <div className="card">
          <h3 style={{ fontWeight: 600, marginBottom: 12 }}>Automation Setup</h3>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
            Run the alert check automatically at shift start by adding a cron job on your server:
          </p>
          <div style={{
            background: "#1a1d21", borderRadius: 6, padding: "12px 16px",
            fontSize: 12, fontFamily: "monospace", color: "#d4d4d4", marginBottom: 16,
          }}>
            <div style={{ color: "#6b7280", marginBottom: 4 }}># /etc/cron.d/lifeandbrand-alerts</div>
            <div># Morning check at 06:30</div>
            <div>30 6 * * * curl -X POST http://localhost:8000/api/v1/alerts/trigger</div>
            <div style={{ marginTop: 6 }}># Afternoon check at 14:00</div>
            <div>0 14 * * * curl -X POST http://localhost:8000/api/v1/alerts/trigger</div>
          </div>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Alerts are automatically deduplicated — running the check twice will not send duplicate messages to the same person for the same batch on the same day.
          </p>

          <h4 style={{ fontWeight: 600, marginTop: 20, marginBottom: 8 }}>Alert Levels</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              { label: "⚠️ Warning", when: "48 hours before expiry", color: "#f59e0b" },
              { label: "🔴 Action Required", when: "24 hours before expiry", color: "#ef4444" },
              { label: "🚨 Urgent", when: "Expires today", color: "#991b1b" },
            ].map(l => (
              <div key={l.label} style={{ fontSize: 13, display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: l.color, fontWeight: 500 }}>{l.label}</span>
                <span style={{ color: "var(--color-text-muted)" }}>{l.when}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Alert history */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ fontWeight: 600 }}>Alert History (last 7 days)</h3>
          <button className="secondary" style={{ fontSize: 12 }} onClick={() => setShowHistory(h => !h)}>
            {showHistory ? "Hide" : "Show"}
          </button>
        </div>
        {showHistory && (
          history.length === 0 ? (
            <p style={{ color: "var(--color-text-muted)" }}>No alerts sent in the last 7 days.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Item</th>
                  <th>Alert Level</th>
                  <th>Recipient</th>
                  <th>Channel</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map(h => (
                  <tr key={h.id}>
                    <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                      {new Date(h.sent_at).toLocaleString()}
                    </td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{h.item_name}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{h.batch_reference}</div>
                    </td>
                    <td style={{ fontSize: 12 }}>{levelLabel(h.alert_level)}</td>
                    <td>{h.contact_name}</td>
                    <td><span className="badge gray" style={{ fontSize: 10 }}>{h.channel}</span></td>
                    <td><span className={`badge ${statusColor[h.status] ?? "gray"}`}>{h.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      {/* Add contact modal */}
      {showForm && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div className="card" style={{ width: 480, padding: 28, maxHeight: "90vh", overflowY: "auto" }}>
            <h3 style={{ fontWeight: 600, marginBottom: 20 }}>Add Alert Recipient</h3>

            <Field label="Full name *">
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
            </Field>
            <Field label="Role (e.g. Head Chef, Floor Manager)">
              <input value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))} />
            </Field>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 8 }}>Notification channels</div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {CHANNEL_OPTIONS.map(ch => (
                  <label key={ch} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={form.active_channels.split(",").includes(ch)}
                      onChange={() => toggleChannel(ch)}
                    />
                    {ch.charAt(0).toUpperCase() + ch.slice(1)}
                  </label>
                ))}
              </div>
            </div>

            {form.active_channels.includes("email") && (
              <Field label="Email address">
                <input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
              </Field>
            )}
            {form.active_channels.includes("whatsapp") && (
              <Field label="WhatsApp number (E.164 format: +27821234567)">
                <input value={form.whatsapp_number} onChange={e => setForm(f => ({ ...f, whatsapp_number: e.target.value }))} placeholder="+27821234567" />
              </Field>
            )}
            {form.active_channels.includes("teams") && (
              <Field label="Teams incoming webhook URL">
                <input value={form.teams_webhook_url} onChange={e => setForm(f => ({ ...f, teams_webhook_url: e.target.value }))} placeholder="https://outlook.office.com/webhook/..." />
              </Field>
            )}

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 8 }}>
                Departments to receive alerts for
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {DEPT_OPTIONS.map(d => (
                  <label key={d} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={form.departments_subscribed.split(",").includes(d)}
                      onChange={() => toggleDept(d)}
                    />
                    {d.charAt(0).toUpperCase() + d.slice(1)}
                  </label>
                ))}
              </div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 6 }}>
                Floor managers should subscribe to Kitchen + Floor so they can push expiring items as specials.
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
              <Field label="Quiet hours start (24h)">
                <input type="number" min={0} max={23} value={form.quiet_hours_start}
                  onChange={e => setForm(f => ({ ...f, quiet_hours_start: parseInt(e.target.value) }))} />
              </Field>
              <Field label="Quiet hours end (24h)">
                <input type="number" min={0} max={23} value={form.quiet_hours_end}
                  onChange={e => setForm(f => ({ ...f, quiet_hours_end: parseInt(e.target.value) }))} />
              </Field>
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                onClick={() => createContact.mutate()}
                disabled={!form.name || createContact.isPending}
              >
                {createContact.isPending ? "Saving..." : "Add Recipient"}
              </button>
              <button className="secondary" onClick={() => { setShowForm(false); setForm(defaultForm); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontWeight: 500, fontSize: 13, marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  );
}
