import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";

interface MeetingSummary {
  id: number;
  team_member_name: string;
  area_manager_name: string;
  meeting_date: string;
  created_at: string;
}

interface MeetingPayload {
  location_id: number;
  team_member_name: string;
  area_manager_name: string;
  meeting_date: string;
  q1_experience: string;
  q2_improvements: string;
  q3_concerns: string;
  q4_growth_next_year: string;
  q5_long_term_goals: string;
  q6_mobility: string;
  q7_workplace_issues: string;
  q8_training: string;
  q9_additional_notes: string;
  team_member_signature: string;
  am_signature: string;
}

const QUESTIONS: { key: keyof MeetingPayload; label: string; prompt: string }[] = [
  {
    key: "q1_experience",
    label: "Q1 — Overall Experience",
    prompt: "How have you found your overall experience working here so far?",
  },
  {
    key: "q2_improvements",
    label: "Q2 — Improvements",
    prompt: "What do you think we could do better as a business or as a team?",
  },
  {
    key: "q3_concerns",
    label: "Q3 — Concerns",
    prompt: "Is there anything about your role or working environment that concerns you?",
  },
  {
    key: "q4_growth_next_year",
    label: "Q4 — Growth in the Next Year",
    prompt: "Where would you like to be in the next year, and how can we support your growth?",
  },
  {
    key: "q5_long_term_goals",
    label: "Q5 — Long-Term Goals",
    prompt: "What are your long-term career goals?",
  },
  {
    key: "q6_mobility",
    label: "Q6 — Mobility",
    prompt: "Would you be open to working at another location within the group if an opportunity arose?",
  },
  {
    key: "q7_workplace_issues",
    label: "Q7 — Workplace Issues",
    prompt: "Have you experienced or witnessed any workplace issues (conduct, culture, fairness) that you'd like to raise?",
  },
  {
    key: "q8_training",
    label: "Q8 — Training & Development",
    prompt: "What training or development would you like to undertake in the next period?",
  },
  {
    key: "q9_additional_notes",
    label: "Q9 — Additional Notes",
    prompt: "Any other comments, ideas, or feedback you'd like to record?",
  },
];

function emptyPayload(): MeetingPayload {
  return {
    location_id: LOCATION_ID,
    team_member_name: "",
    area_manager_name: "",
    meeting_date: new Date().toISOString().slice(0, 10),
    q1_experience: "",
    q2_improvements: "",
    q3_concerns: "",
    q4_growth_next_year: "",
    q5_long_term_goals: "",
    q6_mobility: "",
    q7_workplace_issues: "",
    q8_training: "",
    q9_additional_notes: "",
    team_member_signature: "",
    am_signature: "",
  };
}

export default function OneOnOne() {
  const { orgUnitId: LOCATION_ID } = useAuth();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<MeetingPayload>(emptyPayload);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const { data: meetings = [], isLoading } = useQuery<MeetingSummary[]>({
    queryKey: ["one-on-ones", LOCATION_ID],
    queryFn: () => api.get(`/am/one-on-ones/?location_id=${LOCATION_ID}`).then(r => r.data),
  });

  const { data: detail } = useQuery({
    queryKey: ["one-on-one-detail", viewingId],
    queryFn: () => api.get(`/am/one-on-ones/${viewingId}`).then(r => r.data),
    enabled: viewingId !== null,
  });

  const createMutation = useMutation({
    mutationFn: (payload: MeetingPayload) => api.post("/am/one-on-ones/", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["one-on-ones"] });
      setShowForm(false);
      setForm(emptyPayload());
    },
  });

  function set(field: keyof MeetingPayload, value: string) {
    setForm(f => ({ ...f, [field]: value }));
  }

  if (viewingId !== null && detail) {
    return <DetailView meeting={detail} onBack={() => setViewingId(null)} />;
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>One-on-One Meetings</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            Monthly one-on-one team member meetings conducted by the Area Manager.
          </p>
        </div>
        <button onClick={() => setShowForm(true)}>+ New Meeting</button>
      </div>

      {isLoading ? (
        <div>Loading...</div>
      ) : meetings.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>
          No meetings recorded yet. Click "New Meeting" to start the first one-on-one.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--color-surface-alt, #f9fafb)" }}>
                {["Team Member", "Area Manager", "Meeting Date", "Recorded", ""].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 12, fontWeight: 600, borderBottom: "1px solid var(--color-border)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {meetings.map((m, idx) => (
                <tr key={m.id} style={{ borderBottom: idx < meetings.length - 1 ? "1px solid var(--color-border)" : "none" }}>
                  <td style={{ padding: "12px 16px", fontSize: 13, fontWeight: 500 }}>{m.team_member_name}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13 }}>{m.area_manager_name}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13 }}>{m.meeting_date}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13, color: "var(--color-text-muted)" }}>
                    {new Date(m.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <button className="secondary" style={{ fontSize: 12, padding: "4px 10px" }}
                      onClick={() => setViewingId(m.id)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", overflowY: "auto", zIndex: 100 }}>
          <div className="card" style={{ maxWidth: 680, margin: "32px auto", padding: 32 }}>
            <h2 style={{ fontWeight: 700, fontSize: 18, marginBottom: 20 }}>Monthly One-on-One Meeting</h2>

            {/* Meeting header */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>
              <Field label="Team Member Name *">
                <input value={form.team_member_name} onChange={e => set("team_member_name", e.target.value)} autoFocus />
              </Field>
              <Field label="Area Manager Name *">
                <input value={form.area_manager_name} onChange={e => set("area_manager_name", e.target.value)} />
              </Field>
              <Field label="Meeting Date">
                <input type="date" value={form.meeting_date} onChange={e => set("meeting_date", e.target.value)} />
              </Field>
            </div>

            {/* Questions */}
            <div style={{ fontWeight: 600, fontSize: 14, borderBottom: "2px solid #7c3aed", paddingBottom: 4, marginBottom: 16, color: "#7c3aed" }}>
              Discussion Questions
            </div>
            {QUESTIONS.map(q => (
              <div key={q.key} style={{ marginBottom: 18 }}>
                <label style={{ display: "block", fontWeight: 600, fontSize: 13, marginBottom: 2 }}>{q.label}</label>
                <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: "0 0 6px" }}>{q.prompt}</p>
                <textarea
                  rows={3}
                  value={form[q.key] as string}
                  onChange={e => set(q.key, e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, resize: "vertical", font: "inherit", fontSize: 13 }}
                />
              </div>
            ))}

            {/* Signatures */}
            <div style={{ fontWeight: 600, fontSize: 14, borderBottom: "2px solid #7c3aed", paddingBottom: 4, marginBottom: 12, color: "#7c3aed" }}>
              Signatures
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>
              <Field label="Team Member Signature">
                <input value={form.team_member_signature} onChange={e => set("team_member_signature", e.target.value)} placeholder="Full name as signature" />
              </Field>
              <Field label="AM Signature">
                <input value={form.am_signature} onChange={e => set("am_signature", e.target.value)} placeholder="Area Manager full name" />
              </Field>
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                disabled={!form.team_member_name || !form.area_manager_name || createMutation.isPending}
                onClick={() => createMutation.mutate(form)}
                style={{ background: "#7c3aed" }}
              >
                {createMutation.isPending ? "Saving..." : "Save Meeting Record"}
              </button>
              <button className="secondary" onClick={() => { setShowForm(false); setForm(emptyPayload()); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailView({ meeting, onBack }: { meeting: any; onBack: () => void }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <button className="secondary" onClick={onBack}>← Back</button>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>
            One-on-One — {meeting.team_member_name}
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>
            {meeting.meeting_date} · AM: {meeting.area_manager_name}
          </p>
        </div>
      </div>

      <div className="card" style={{ padding: 24 }}>
        {QUESTIONS.map(q => {
          const answer = meeting[q.key];
          if (!answer) return null;
          return (
            <div key={q.key} style={{ marginBottom: 20, paddingBottom: 20, borderBottom: "1px solid var(--color-border)" }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: "#7c3aed", marginBottom: 2 }}>{q.label}</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>{q.prompt}</div>
              <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{answer}</div>
            </div>
          );
        })}

        {(meeting.team_member_signature || meeting.am_signature) && (
          <div style={{ display: "flex", gap: 32, fontSize: 13, paddingTop: 4 }}>
            {meeting.team_member_signature && (
              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>Team Member Signature</div>
                <div style={{ fontWeight: 500 }}>{meeting.team_member_signature}</div>
              </div>
            )}
            {meeting.am_signature && (
              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>AM Signature</div>
                <div style={{ fontWeight: 500 }}>{meeting.am_signature}</div>
              </div>
            )}
          </div>
        )}
      </div>
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
