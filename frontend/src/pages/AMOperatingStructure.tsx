import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";

const AM_NAME_FALLBACK = "Area Manager";

type Frequency = "daily" | "weekly" | "monthly" | "adhoc";

interface Task { id: number; frequency: Frequency; order_num: number; title: string; }
interface Entry {
  id: number; task_id: number; period_date: string;
  completed: boolean; completed_by: string | null; completed_at: string | null; notes: string | null;
  validated: boolean; validated_by: string | null; validated_at: string | null;
}
interface TaskWithEntry { task: Task; entry: Entry | null; }
interface Summary { total: number; completed: number; validated: number; period_date: string; }

const FREQ_CONFIG: Record<Frequency, { label: string; color: string; periodLabel: string }> = {
  daily:   { label: "Daily",   color: "#2563eb", periodLabel: "Today" },
  weekly:  { label: "Weekly",  color: "#16a34a", periodLabel: "This Week" },
  monthly: { label: "Monthly", color: "#7c3aed", periodLabel: "This Month" },
  adhoc:   { label: "Ad Hoc",  color: "#dc2626", periodLabel: "Ongoing" },
};

export default function AMOperatingStructure() {
  const { orgUnitId: LOCATION_ID, user } = useAuth();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<Frequency>("daily");
  const [completingTask, setCompletingTask] = useState<Task | null>(null);
  const [completedBy, setCompletedBy] = useState(user?.name || AM_NAME_FALLBACK);
  const [completionNotes, setCompletionNotes] = useState("");
  const [validatingEntry, setValidatingEntry] = useState<Entry | null>(null);
  const [validatedBy, setValidatedBy] = useState("");

  const { data: summary } = useQuery<Record<Frequency, Summary>>({
    queryKey: ["am-checklist-summary", LOCATION_ID],
    queryFn: () => api.get(`/am/checklist/summary?location_id=${LOCATION_ID}`).then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: items = [], isLoading } = useQuery<TaskWithEntry[]>({
    queryKey: ["am-checklist-period", LOCATION_ID, activeTab],
    queryFn: () => api.get(`/am/checklist/period?location_id=${LOCATION_ID}&frequency=${activeTab}`).then(r => r.data),
  });

  const completeMutation = useMutation({
    mutationFn: ({ taskId, completed_by, notes }: { taskId: number; completed_by: string; notes?: string }) =>
      api.post(`/am/checklist/tasks/${taskId}/complete`, { location_id: LOCATION_ID, completed_by, notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["am-checklist-period", LOCATION_ID, activeTab] });
      qc.invalidateQueries({ queryKey: ["am-checklist-summary"] });
      setCompletingTask(null);
      setCompletionNotes("");
    },
  });

  const validateMutation = useMutation({
    mutationFn: ({ entryId, validated_by }: { entryId: number; validated_by: string }) =>
      api.post(`/am/checklist/entries/${entryId}/validate`, { validated_by }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["am-checklist-period", LOCATION_ID, activeTab] });
      qc.invalidateQueries({ queryKey: ["am-checklist-summary"] });
      setValidatingEntry(null);
      setValidatedBy("");
    },
  });

  const undoMutation = useMutation({
    mutationFn: (taskId: number) =>
      api.post(`/am/checklist/tasks/${taskId}/undo?location_id=${LOCATION_ID}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["am-checklist-period", LOCATION_ID, activeTab] });
      qc.invalidateQueries({ queryKey: ["am-checklist-summary"] });
    },
  });

  const cfg = FREQ_CONFIG[activeTab];
  const s = summary?.[activeTab];

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>AM Operating Structure</h1>
      <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginBottom: 24 }}>
        Area Manager checklist — tasks require AM completion and Regional Manager validation.
      </p>

      {/* Summary progress bars */}
      {summary && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
          {(Object.keys(FREQ_CONFIG) as Frequency[]).map(freq => {
            const fs = summary[freq];
            const cfg2 = FREQ_CONFIG[freq];
            const pct = fs.total > 0 ? Math.round((fs.completed / fs.total) * 100) : 0;
            return (
              <button
                key={freq}
                onClick={() => setActiveTab(freq)}
                style={{
                  background: activeTab === freq ? cfg2.color : "var(--color-surface)",
                  border: `2px solid ${cfg2.color}`,
                  borderRadius: 8, padding: "12px 16px", cursor: "pointer", textAlign: "left",
                  color: activeTab === freq ? "#fff" : "var(--color-text)",
                  transition: "all 0.15s",
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{cfg2.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{fs.completed}/{fs.total}</div>
                <div style={{ fontSize: 11, opacity: 0.8, marginBottom: 6 }}>{pct}% complete · {fs.validated} validated</div>
                <div style={{ height: 4, background: activeTab === freq ? "rgba(255,255,255,0.3)" : "#e5e7eb", borderRadius: 2, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${pct}%`, background: activeTab === freq ? "#fff" : cfg2.color, borderRadius: 2 }} />
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Task list */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{
          padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          background: cfg.color, borderRadius: "8px 8px 0 0",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span style={{ color: "#fff", fontWeight: 600 }}>{cfg.label} Tasks — {cfg.periodLabel}</span>
          {s && (
            <span style={{ color: "rgba(255,255,255,0.85)", fontSize: 13 }}>
              {s.completed}/{s.total} completed · {s.validated} validated by RM
            </span>
          )}
        </div>

        {isLoading ? (
          <div style={{ padding: 24 }}>Loading...</div>
        ) : items.map(({ task, entry }, idx) => (
          <div key={task.id} style={{
            display: "flex", alignItems: "flex-start", padding: "14px 20px",
            borderBottom: idx < items.length - 1 ? "1px solid var(--color-border)" : "none",
            background: entry?.completed ? (entry.validated ? "#f0fdf4" : "#fffbeb") : "transparent",
          }}>
            {/* Order number */}
            <div style={{
              width: 28, height: 28, borderRadius: "50%", flexShrink: 0, marginRight: 14, marginTop: 2,
              background: entry?.validated ? "#16a34a" : entry?.completed ? "#f59e0b" : "#e5e7eb",
              color: entry?.completed ? "#fff" : "#6b7280",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 12, fontWeight: 700,
            }}>
              {task.order_num}
            </div>

            {/* Task content */}
            <div style={{ flex: 1 }}>
              <div style={{
                fontSize: 14,
                color: entry?.completed ? "var(--color-text)" : "var(--color-text)",
                textDecoration: entry?.validated ? "line-through" : "none",
                opacity: entry?.validated ? 0.6 : 1,
              }}>
                {task.title}
              </div>

              {entry?.completed && (
                <div style={{ marginTop: 4, fontSize: 12, color: "var(--color-text-muted)", display: "flex", gap: 16 }}>
                  <span>✓ {entry.completed_by} · {entry.completed_at ? new Date(entry.completed_at).toLocaleString() : ""}</span>
                  {entry.notes && <span>Note: {entry.notes}</span>}
                  {entry.validated && <span style={{ color: "#16a34a" }}>✓ Validated by {entry.validated_by}</span>}
                </div>
              )}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 12 }}>
              {!entry?.completed ? (
                <button style={{ fontSize: 12, padding: "5px 12px", background: cfg.color }}
                  onClick={() => setCompletingTask(task)}>
                  Mark Done
                </button>
              ) : !entry.validated ? (
                <>
                  <button style={{ fontSize: 12, padding: "5px 12px" }}
                    onClick={() => setValidatingEntry(entry)}>
                    Validate (RM)
                  </button>
                  <button className="secondary" style={{ fontSize: 12, padding: "5px 12px" }}
                    onClick={() => undoMutation.mutate(task.id)}>
                    Undo
                  </button>
                </>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {/* Complete modal */}
      {completingTask && (
        <Modal title={`Complete Task #${completingTask.order_num}`} onClose={() => setCompletingTask(null)}>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
            {completingTask.title}
          </p>
          <Field label="Completed by">
            <input value={completedBy} onChange={e => setCompletedBy(e.target.value)} />
          </Field>
          <Field label="Notes (optional)">
            <textarea rows={2} value={completionNotes} onChange={e => setCompletionNotes(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, resize: "vertical", font: "inherit" }} />
          </Field>
          <div style={{ display: "flex", gap: 10 }}>
            <button style={{ background: cfg.color }} disabled={!completedBy || completeMutation.isPending}
              onClick={() => completeMutation.mutate({ taskId: completingTask.id, completed_by: completedBy, notes: completionNotes || undefined })}>
              {completeMutation.isPending ? "Saving..." : "Confirm Complete"}
            </button>
            <button className="secondary" onClick={() => setCompletingTask(null)}>Cancel</button>
          </div>
        </Modal>
      )}

      {/* Validate modal */}
      {validatingEntry && (
        <Modal title="RM Validation" onClose={() => setValidatingEntry(null)}>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
            Confirm this task has been completed to standard.
          </p>
          <Field label="Regional Manager name">
            <input value={validatedBy} onChange={e => setValidatedBy(e.target.value)} autoFocus />
          </Field>
          <div style={{ display: "flex", gap: 10 }}>
            <button style={{ background: "#16a34a" }} disabled={!validatedBy || validateMutation.isPending}
              onClick={() => validateMutation.mutate({ entryId: validatingEntry.id, validated_by: validatedBy })}>
              {validateMutation.isPending ? "Saving..." : "Validate"}
            </button>
            <button className="secondary" onClick={() => setValidatingEntry(null)}>Cancel</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 440, padding: 28 }}>
        <h3 style={{ fontWeight: 600, marginBottom: 16 }}>{title}</h3>
        {children}
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
