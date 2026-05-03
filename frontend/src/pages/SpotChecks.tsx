import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import type { SpotCheckSession, SpotCheckItem, Department } from "../types";

const LOCATION_ID = 1; // TODO: replace with auth context
const DEPARTMENTS: Department[] = ["bar", "kitchen", "floor"];
const DEPT_LABELS: Record<Department, string> = { bar: "Bar", kitchen: "Kitchen", floor: "Floor", general: "General" };

export default function SpotChecks() {
  const qc = useQueryClient();
  const [activeSession, setActiveSession] = useState<SpotCheckSession | null>(null);
  const [countingItem, setCountingItem] = useState<SpotCheckItem | null>(null);
  const [countValue, setCountValue] = useState("");
  const [countedBy, setCountedBy] = useState("");
  const [countNotes, setCountNotes] = useState("");

  const { data: sessions = [], isLoading } = useQuery<SpotCheckSession[]>({
    queryKey: ["spot-checks-today", LOCATION_ID],
    queryFn: () => api.get(`/spot-checks/today?location_id=${LOCATION_ID}`).then((r) => r.data),
    refetchInterval: 60_000,
  });

  const generateMutation = useMutation({
    mutationFn: (payload: { department: Department; session_slot: number }) =>
      api.post("/spot-checks/generate", {
        location_id: LOCATION_ID,
        ...payload,
        n_items: 5,
      }).then((r) => r.data as SpotCheckSession),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ["spot-checks-today"] });
      setActiveSession(session);
    },
  });

  const countMutation = useMutation({
    mutationFn: ({ sessionId, itemId, actual_quantity, counted_by, notes }: {
      sessionId: number; itemId: number; actual_quantity: number; counted_by: string; notes?: string;
    }) =>
      api.post(`/spot-checks/${sessionId}/items/${itemId}/count`, {
        actual_quantity,
        counted_by,
        notes,
      }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["spot-checks-today"] });
      setCountingItem(null);
      setCountValue("");
      setCountNotes("");
      // Refresh active session
      if (activeSession) {
        api.get(`/spot-checks/${activeSession.id}`).then((r) => setActiveSession(r.data));
      }
    },
  });

  const todayExists = (dept: Department, slot: number) =>
    sessions.some((s) => s.department === dept && s.session_slot === slot);

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>Daily Spot Checks</h1>
      <p style={{ color: "var(--color-text-muted)", marginBottom: 24 }}>
        5 items per department per session — selected by sales velocity, variance history, and rotation fairness.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 28 }}>
        {DEPARTMENTS.map((dept) => (
          <DeptCard
            key={dept}
            department={dept}
            sessions={sessions.filter((s) => s.department === dept)}
            onSelect={setActiveSession}
            activeId={activeSession?.id}
            onGenerate={(slot) => generateMutation.mutate({ department: dept, session_slot: slot })}
            generating={generateMutation.isPending}
            todayExists={todayExists}
          />
        ))}
      </div>

      {activeSession && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
            <h3 style={{ fontWeight: 600 }}>
              {DEPT_LABELS[activeSession.department]} — Slot {activeSession.session_slot} — {activeSession.session_date}
            </h3>
            <StatusBadge status={activeSession.status} />
          </div>

          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Category</th>
                <th>Last Checked</th>
                <th>Theoretical</th>
                <th>Actual Count</th>
                <th>Variance</th>
                <th>Value</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {activeSession.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{item.item_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{item.item_code}</div>
                  </td>
                  <td>{item.item_category}</td>
                  <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    {item.days_since_last_check !== null
                      ? item.days_since_last_check === 14
                        ? "14+ days"
                        : `${item.days_since_last_check}d ago`
                      : "Never"}
                  </td>
                  <td>{item.theoretical_quantity?.toFixed(2) ?? "—"} {item.unit_abbreviation}</td>
                  <td>
                    {item.actual_quantity !== null
                      ? `${item.actual_quantity.toFixed(2)} ${item.unit_abbreviation}`
                      : <span style={{ color: "var(--color-text-muted)" }}>Pending</span>}
                  </td>
                  <td>
                    {item.variance_quantity !== null ? (
                      <span className={item.variance_quantity < 0 ? "variance-negative" : "variance-positive"}>
                        {item.variance_quantity > 0 ? "+" : ""}{item.variance_quantity.toFixed(2)}
                        {item.variance_pct !== null && (
                          <span style={{ fontWeight: 400, fontSize: 11 }}> ({item.variance_pct.toFixed(1)}%)</span>
                        )}
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    {item.variance_value !== null ? (
                      <span className={item.variance_value < 0 ? "variance-negative" : "variance-positive"}>
                        {item.variance_value > 0 ? "+" : ""}R{item.variance_value.toFixed(2)}
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    {item.actual_quantity === null && (
                      <button
                        className="secondary"
                        style={{ fontSize: 12 }}
                        onClick={() => { setCountingItem(item); setCountValue(""); }}
                      >
                        Count
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Count entry modal */}
      {countingItem && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div className="card" style={{ width: 380, padding: 28 }}>
            <h3 style={{ fontWeight: 600, marginBottom: 4 }}>Count: {countingItem.item_name}</h3>
            <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginBottom: 20 }}>
              Theoretical: {countingItem.theoretical_quantity?.toFixed(2) ?? "?"} {countingItem.unit_abbreviation}
            </p>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>
                Actual count ({countingItem.unit_abbreviation})
              </label>
              <input
                type="number"
                step="0.01"
                value={countValue}
                onChange={(e) => setCountValue(e.target.value)}
                autoFocus
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 16 }}
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>
                Your name
              </label>
              <input
                type="text"
                value={countedBy}
                onChange={(e) => setCountedBy(e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 14 }}
              />
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>
                Notes (optional)
              </label>
              <input
                type="text"
                value={countNotes}
                onChange={(e) => setCountNotes(e.target.value)}
                placeholder="e.g. bottles in ice bucket not counted"
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 14 }}
              />
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                disabled={!countValue || !countedBy || countMutation.isPending}
                onClick={() => {
                  if (!activeSession || !countingItem) return;
                  countMutation.mutate({
                    sessionId: activeSession.id,
                    itemId: countingItem.item_id,
                    actual_quantity: parseFloat(countValue),
                    counted_by: countedBy,
                    notes: countNotes || undefined,
                  });
                }}
              >
                {countMutation.isPending ? "Saving..." : "Submit Count"}
              </button>
              <button className="secondary" onClick={() => setCountingItem(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DeptCard({
  department, sessions, onSelect, activeId, onGenerate, generating, todayExists,
}: {
  department: Department;
  sessions: SpotCheckSession[];
  onSelect: (s: SpotCheckSession) => void;
  activeId: number | undefined;
  onGenerate: (slot: number) => void;
  generating: boolean;
  todayExists: (dept: Department, slot: number) => boolean;
}) {
  const label = { bar: "Bar", kitchen: "Kitchen", floor: "Floor", general: "General" }[department];
  const slot1 = sessions.find((s) => s.session_slot === 1);
  const slot2 = sessions.find((s) => s.session_slot === 2);
  const completedToday = sessions.filter((s) => s.status === "complete").length;

  return (
    <div className="card">
      <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 12 }}>{label}</div>
      <div style={{ color: "var(--color-text-muted)", fontSize: 12, marginBottom: 14 }}>
        {completedToday}/2 sessions complete today
      </div>

      {[1, 2].map((slot) => {
        const session = slot === 1 ? slot1 : slot2;
        return (
          <div key={slot} style={{ marginBottom: 8 }}>
            {session ? (
              <button
                className="secondary"
                style={{
                  width: "100%", textAlign: "left",
                  background: activeId === session.id ? "#f0f4ff" : undefined,
                  borderColor: activeId === session.id ? "var(--color-primary)" : undefined,
                }}
                onClick={() => onSelect(session)}
              >
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                  Slot {slot}:{" "}
                </span>
                <StatusBadge status={session.status} />
                <span style={{ fontSize: 12, marginLeft: 6 }}>
                  {session.items.filter((i) => i.actual_quantity !== null).length}/{session.items.length} counted
                </span>
              </button>
            ) : (
              <button
                onClick={() => onGenerate(slot)}
                disabled={generating || (slot === 2 && !todayExists(department, 1))}
                style={{ width: "100%", fontSize: 13 }}
                title={slot === 2 && !todayExists(department, 1) ? "Complete morning session first" : undefined}
              >
                {generating ? "..." : `Generate Slot ${slot}`}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

const statusColor: Record<string, string> = {
  pending: "yellow", partial: "blue", complete: "green", missed: "red",
};

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${statusColor[status] ?? "gray"}`}>{status}</span>;
}
