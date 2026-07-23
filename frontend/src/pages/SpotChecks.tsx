import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import type { SpotCheckSession, SpotCheckItem, SpotCheckBatchCount, Department, ItemBatch } from "../types";
import { useAuth } from "../contexts/AuthContext";
const DEPARTMENTS: Department[] = ["bar", "kitchen", "floor"];
const DEPT_LABELS: Record<Department, string> = { bar: "Bar", kitchen: "Kitchen", floor: "Floor", general: "General" };

export default function SpotChecks() {
  const { orgUnitId: LOCATION_ID } = useAuth();
  const qc = useQueryClient();
  const [activeSession, setActiveSession] = useState<SpotCheckSession | null>(null);
  const [countModal, setCountModal] = useState<{ item: SpotCheckItem; batch?: SpotCheckBatchCount } | null>(null);
  const [countValue, setCountValue] = useState("");
  const [countedBy, setCountedBy] = useState("");
  const [countNotes, setCountNotes] = useState("");

  const { data: sessions = [], isLoading } = useQuery<SpotCheckSession[]>({
    queryKey: ["spot-checks-today", LOCATION_ID],
    queryFn: () => api.get(`/spot-checks/today?location_id=${LOCATION_ID}`).then(r => r.data),
    refetchInterval: 60_000,
  });

  const { data: expiringBatches = [] } = useQuery<ItemBatch[]>({
    queryKey: ["expiring-batches", LOCATION_ID],
    queryFn: () => api.get(`/batches/expiring?location_id=${LOCATION_ID}&within_days=2`).then(r => r.data),
    refetchInterval: 300_000,
  });

  const generateMutation = useMutation({
    mutationFn: (p: { department: Department; session_slot: number }) =>
      api.post("/spot-checks/generate", { location_id: LOCATION_ID, ...p, base_n: 5 })
        .then(r => r.data as SpotCheckSession),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ["spot-checks-today"] });
      setActiveSession(session);
    },
  });

  const countMutation = useMutation({
    mutationFn: (p: { sessionId: number; itemId: number; actual_quantity: number; counted_by: string; notes?: string }) =>
      api.post(`/spot-checks/${p.sessionId}/items/${p.itemId}/count`, {
        actual_quantity: p.actual_quantity, counted_by: p.counted_by, notes: p.notes,
      }).then(r => r.data),
    onSuccess: () => afterCount(),
  });

  const batchCountMutation = useMutation({
    mutationFn: (p: { sessionId: number; itemId: number; batch_id: number; actual_quantity: number; counted_by: string; notes?: string }) =>
      api.post(`/spot-checks/${p.sessionId}/items/${p.itemId}/batch-count`, {
        batch_id: p.batch_id, actual_quantity: p.actual_quantity, counted_by: p.counted_by, notes: p.notes,
      }).then(r => r.data),
    onSuccess: () => afterCount(),
  });

  const afterCount = () => {
    qc.invalidateQueries({ queryKey: ["spot-checks-today"] });
    setCountModal(null);
    setCountValue("");
    setCountNotes("");
    if (activeSession) {
      api.get(`/spot-checks/${activeSession.id}`).then(r => setActiveSession(r.data));
    }
  };

  const todayExists = (dept: Department, slot: number) =>
    sessions.some(s => s.department === dept && s.session_slot === slot);

  const openCount = (item: SpotCheckItem, batch?: SpotCheckBatchCount) => {
    setCountModal({ item, batch });
    setCountValue("");
    setCountNotes("");
  };

  const submitCount = () => {
    if (!countModal || !activeSession || !countValue || !countedBy) return;
    const { item, batch } = countModal;
    if (batch) {
      batchCountMutation.mutate({
        sessionId: activeSession.id, itemId: item.id,
        batch_id: batch.batch_id, actual_quantity: parseFloat(countValue),
        counted_by: countedBy, notes: countNotes || undefined,
      });
    } else {
      countMutation.mutate({
        sessionId: activeSession.id, itemId: item.id,
        actual_quantity: parseFloat(countValue),
        counted_by: countedBy, notes: countNotes || undefined,
      });
    }
  };

  if (isLoading) return <p>Loading...</p>;

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>Daily Spot Checks</h1>
      <p style={{ color: "var(--color-text-muted)", marginBottom: expiringBatches.length ? 16 : 24, fontSize: 13 }}>
        Items selected by: sales velocity · item value · variance history · 7-day rotation guarantee
      </p>

      {/* Expiry alerts */}
      {expiringBatches.length > 0 && (
        <div style={{
          background: "#fef3c7", border: "1px solid #f59e0b", borderRadius: 8,
          padding: "12px 16px", marginBottom: 24,
        }}>
          <div style={{ fontWeight: 600, color: "#92400e", marginBottom: 8 }}>
            Freshness Alert — {expiringBatches.length} batch{expiringBatches.length > 1 ? "es" : ""} expiring within 48 hours
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {expiringBatches.map(b => (
              <div key={b.id} style={{
                background: b.days_until_expiry !== null && b.days_until_expiry < 0 ? "#fee2e2" : "#fff",
                border: `1px solid ${b.days_until_expiry !== null && b.days_until_expiry < 0 ? "#fca5a5" : "#fcd34d"}`,
                borderRadius: 6, padding: "6px 10px", fontSize: 13,
              }}>
                <strong>{b.item_name}</strong>{" "}
                <span style={{ color: "var(--color-text-muted)" }}>
                  {b.batch_reference} · {b.quantity_remaining} remaining ·{" "}
                  {b.days_until_expiry !== null && b.days_until_expiry < 0
                    ? <span style={{ color: "var(--color-danger)", fontWeight: 600 }}>EXPIRED {Math.abs(b.days_until_expiry)}d ago</span>
                    : b.days_until_expiry === 0
                      ? <span style={{ color: "#d97706", fontWeight: 600 }}>Expires TODAY</span>
                      : <span>Expires in {b.days_until_expiry}d</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Department cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 28 }}>
        {DEPARTMENTS.map(dept => (
          <DeptCard
            key={dept}
            department={dept}
            sessions={sessions.filter(s => s.department === dept)}
            onSelect={setActiveSession}
            activeId={activeSession?.id}
            onGenerate={slot => generateMutation.mutate({ department: dept, session_slot: slot })}
            generating={generateMutation.isPending}
            todayExists={todayExists}
          />
        ))}
      </div>

      {/* Active session detail */}
      {activeSession && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
            <div>
              <h3 style={{ fontWeight: 600 }}>
                {DEPT_LABELS[activeSession.department]} — Slot {activeSession.session_slot}
              </h3>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 2 }}>
                {activeSession.items.filter(i => isCounted(i)).length}/{activeSession.items.length} counted
                {activeSession.overdue_count > 0 && (
                  <span style={{ color: "var(--color-danger)", marginLeft: 10 }}>
                    {activeSession.overdue_count} overdue (7-day rule)
                  </span>
                )}
              </div>
            </div>
            <StatusBadge status={activeSession.status} />
          </div>

          {activeSession.items.map(item => (
            <ItemRow key={item.id} item={item} onCount={openCount} />
          ))}
        </div>
      )}

      {/* Count modal */}
      {countModal && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div className="card" style={{ width: 400, padding: 28 }}>
            <h3 style={{ fontWeight: 600, marginBottom: 4 }}>{countModal.item.item_name}</h3>
            {countModal.batch ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
                Batch: <strong>{countModal.batch.batch_reference}</strong>
                {" · "}Received: {countModal.batch.received_date}
                {countModal.batch.best_before_date && (
                  <span style={{
                    marginLeft: 8, fontWeight: 600,
                    color: (countModal.batch.days_until_expiry ?? 99) <= 1 ? "var(--color-danger)" : "var(--color-text)",
                  }}>
                    Best before: {countModal.batch.best_before_date}
                    {countModal.batch.days_until_expiry !== null && (
                      ` (${countModal.batch.days_until_expiry < 0 ? "EXPIRED" : `${countModal.batch.days_until_expiry}d left`})`
                    )}
                  </span>
                )}
                <div style={{ marginTop: 4 }}>
                  Expected: <strong>{countModal.batch.expected_quantity?.toFixed(2)} {countModal.item.unit_abbreviation}</strong>
                </div>
              </div>
            ) : (
              <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginBottom: 16 }}>
                Theoretical: {countModal.item.theoretical_quantity?.toFixed(2) ?? "?"} {countModal.item.unit_abbreviation}
              </p>
            )}

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>
                Actual count ({countModal.item.unit_abbreviation})
              </label>
              <input
                type="number" step="0.01" value={countValue} autoFocus
                onChange={e => setCountValue(e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 18 }}
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>Your name</label>
              <input
                type="text" value={countedBy}
                onChange={e => setCountedBy(e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 14 }}
              />
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ display: "block", fontWeight: 500, marginBottom: 4, fontSize: 13 }}>Notes (optional)</label>
              <input
                type="text" value={countNotes}
                onChange={e => setCountNotes(e.target.value)}
                placeholder="e.g. 2 portions in service"
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, fontSize: 14 }}
              />
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                disabled={!countValue || !countedBy || countMutation.isPending || batchCountMutation.isPending}
                onClick={submitCount}
              >
                Submit Count
              </button>
              <button className="secondary" onClick={() => setCountModal(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ItemRow({ item, onCount }: {
  item: SpotCheckItem;
  onCount: (item: SpotCheckItem, batch?: SpotCheckBatchCount) => void;
}) {
  const counted = isCounted(item);

  return (
    <div style={{
      borderBottom: "1px solid var(--color-border)",
      padding: "12px 0",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 500 }}>{item.item_name}</span>
            {item.is_overdue && (
              <span className="badge red" style={{ fontSize: 10 }}>OVERDUE</span>
            )}
            {item.is_perishable && (
              <span className="badge yellow" style={{ fontSize: 10 }}>PERISHABLE</span>
            )}
            {counted && <span className="badge green" style={{ fontSize: 10 }}>COUNTED</span>}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>
            {item.item_code} · {item.item_category}
            {item.unit_cost !== null && ` · R${item.unit_cost.toFixed(2)}/${item.unit_abbreviation}`}
            {item.days_since_last_check !== null && ` · Last checked ${item.days_since_last_check}d ago`}
          </div>

          {/* Variance result for non-perishable counted items */}
          {!item.is_perishable && counted && item.variance_quantity !== null && (
            <div style={{ marginTop: 4, fontSize: 13 }}>
              Count: <strong>{item.actual_quantity?.toFixed(2)} {item.unit_abbreviation}</strong>
              {" · "}
              <span className={item.variance_quantity < 0 ? "variance-negative" : "variance-positive"}>
                {item.variance_quantity > 0 ? "+" : ""}{item.variance_quantity.toFixed(2)} {item.unit_abbreviation}
                {item.variance_pct !== null && ` (${item.variance_pct.toFixed(1)}%)`}
                {item.variance_value !== null && ` · R${item.variance_value.toFixed(2)}`}
              </span>
            </div>
          )}
        </div>

        {/* Non-perishable count button */}
        {!item.is_perishable && !counted && (
          <button className="secondary" style={{ fontSize: 12, flexShrink: 0 }} onClick={() => onCount(item)}>
            Count
          </button>
        )}
      </div>

      {/* Perishable: show batch rows */}
      {item.is_perishable && item.batch_counts.length > 0 && (
        <div style={{ marginTop: 10, paddingLeft: 16 }}>
          {item.batch_counts.map(bc => (
            <BatchRow key={bc.id} bc={bc} item={item} onCount={onCount} />
          ))}
          {/* Rolled-up total once all batches counted */}
          {item.batch_counts.every(bc => bc.actual_quantity !== null) && item.variance_quantity !== null && (
            <div style={{ marginTop: 6, fontSize: 13, fontWeight: 500 }}>
              Total variance:{" "}
              <span className={item.variance_quantity < 0 ? "variance-negative" : "variance-positive"}>
                {item.variance_quantity > 0 ? "+" : ""}{item.variance_quantity.toFixed(2)} {item.unit_abbreviation}
                {item.variance_value !== null && ` (R${item.variance_value.toFixed(2)})`}
              </span>
            </div>
          )}
        </div>
      )}

      {item.is_perishable && item.batch_counts.length === 0 && (
        <div style={{ marginTop: 6, fontSize: 13, color: "var(--color-text-muted)", paddingLeft: 16 }}>
          No active batches on hand
        </div>
      )}
    </div>
  );
}

function BatchRow({ bc, item, onCount }: {
  bc: SpotCheckBatchCount;
  item: SpotCheckItem;
  onCount: (item: SpotCheckItem, batch: SpotCheckBatchCount) => void;
}) {
  const expired = bc.days_until_expiry !== null && bc.days_until_expiry < 0;
  const expiringSoon = bc.days_until_expiry !== null && bc.days_until_expiry >= 0 && bc.days_until_expiry <= 1;

  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "6px 10px", marginBottom: 4, borderRadius: 4,
      background: expired ? "#fee2e2" : expiringSoon ? "#fef3c7" : "#f8f9fa",
      border: `1px solid ${expired ? "#fca5a5" : expiringSoon ? "#fcd34d" : "var(--color-border)"}`,
    }}>
      <div style={{ fontSize: 13 }}>
        <span style={{ fontWeight: 500 }}>{bc.batch_reference}</span>
        <span style={{ color: "var(--color-text-muted)", marginLeft: 10 }}>
          Rcvd {bc.received_date}
        </span>
        {bc.best_before_date && (
          <span style={{ marginLeft: 10, fontWeight: expired || expiringSoon ? 700 : 400, color: expired ? "var(--color-danger)" : expiringSoon ? "#d97706" : "inherit" }}>
            BB: {bc.best_before_date}
            {bc.days_until_expiry !== null && (
              expired ? " ⚠ EXPIRED" : bc.days_until_expiry === 0 ? " ⚠ Today" : ` (${bc.days_until_expiry}d)`
            )}
          </span>
        )}
        <span style={{ marginLeft: 10, color: "var(--color-text-muted)" }}>
          Expected: {bc.expected_quantity?.toFixed(2)} {item.unit_abbreviation}
        </span>
        {bc.actual_quantity !== null && (
          <span style={{ marginLeft: 10 }}>
            Counted: <strong>{bc.actual_quantity.toFixed(2)}</strong>
            {bc.variance_quantity !== null && (
              <span className={bc.variance_quantity < 0 ? "variance-negative" : "variance-positive"} style={{ marginLeft: 6 }}>
                ({bc.variance_quantity > 0 ? "+" : ""}{bc.variance_quantity.toFixed(2)})
              </span>
            )}
          </span>
        )}
      </div>
      {bc.actual_quantity === null && (
        <button className="secondary" style={{ fontSize: 11, padding: "4px 10px", flexShrink: 0 }} onClick={() => onCount(item, bc)}>
          Count
        </button>
      )}
    </div>
  );
}

function DeptCard({ department, sessions, onSelect, activeId, onGenerate, generating, todayExists }: {
  department: Department;
  sessions: SpotCheckSession[];
  onSelect: (s: SpotCheckSession) => void;
  activeId: number | undefined;
  onGenerate: (slot: number) => void;
  generating: boolean;
  todayExists: (dept: Department, slot: number) => boolean;
}) {
  const label = DEPT_LABELS[department];
  const completedToday = sessions.filter(s => s.status === "complete").length;
  const overdueTotal = sessions.reduce((n, s) => n + s.overdue_count, 0);

  return (
    <div className="card">
      <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: overdueTotal ? 4 : 14 }}>
        {completedToday}/2 sessions complete today
      </div>
      {overdueTotal > 0 && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: 14 }}>
          {overdueTotal} overdue item{overdueTotal > 1 ? "s" : ""} in queue
        </div>
      )}
      {[1, 2].map(slot => {
        const session = sessions.find(s => s.session_slot === slot);
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
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Slot {slot}: </span>
                <StatusBadge status={session.status} />
                <span style={{ fontSize: 12, marginLeft: 6 }}>
                  {session.items.filter(i => isCounted(i)).length}/{session.items.length}
                </span>
              </button>
            ) : (
              <button
                onClick={() => onGenerate(slot)}
                disabled={generating || (slot === 2 && !todayExists(department, 1))}
                style={{ width: "100%", fontSize: 13 }}
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

function isCounted(item: SpotCheckItem): boolean {
  if (item.is_perishable) {
    return item.batch_counts.length > 0 && item.batch_counts.every(bc => bc.actual_quantity !== null);
  }
  return item.actual_quantity !== null;
}

const statusColor: Record<string, string> = {
  pending: "yellow", partial: "blue", complete: "green", missed: "red",
};

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${statusColor[status] ?? "gray"}`}>{status}</span>;
}
