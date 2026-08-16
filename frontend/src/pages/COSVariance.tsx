import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";
import SiteSelector from "../components/SiteSelector";

type FlagCause = "counting_swap" | "timing" | "spillage" | "process_failure" | "immediate" | "known_baseline" | null;

interface CosSummary {
  actual_cos_pct: number | null;
  theoretical_cos_pct: number | null;
  variance_pct: number | null;
  actual_usage_value: number | null;
  theoretical_usage_value: number | null;
}

interface CosFlag {
  id: number;
  item_name: string;
  actual_qty: number | null;
  theoretical_qty: number | null;
  variance_qty: number | null;
  variance_value: number | null;
  cause: FlagCause;
  status: "open" | "dismissed";
}

interface CosVarianceData {
  summary: CosSummary | null;
  flags: CosFlag[] | null;
}

const CAUSE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  counting_swap:   { label: "Counting Swap",   color: "#7c3aed", bg: "#f5f3ff" },
  timing:          { label: "Timing",          color: "#2563eb", bg: "#eff6ff" },
  spillage:        { label: "Spillage",        color: "#d97706", bg: "#fffbeb" },
  process_failure: { label: "Process Failure", color: "#dc2626", bg: "#fef2f2" },
  immediate:       { label: "Immediate",       color: "#db2777", bg: "#fdf2f8" },
  known_baseline:  { label: "Known Baseline",  color: "#16a34a", bg: "#f0fdf4" },
};

function formatZAR(value: number | null | undefined): string {
  if (value == null) return "—";
  return "R " + Math.round(value).toLocaleString("en-ZA").replace(/,/g, " ");
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(1)}%`;
}

function formatQty(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-ZA", { maximumFractionDigits: 2 }).replace(/,/g, " ");
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function CauseBadge({ cause }: { cause: FlagCause }) {
  const cfg = cause ? CAUSE_CONFIG[cause] : null;
  if (!cfg) {
    return (
      <span style={{ display: "inline-block", padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, color: "#6b7280", background: "#f3f4f6" }}>
        Uncategorised
      </span>
    );
  }
  return (
    <span style={{ display: "inline-block", padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, color: cfg.color, background: cfg.bg }}>
      {cfg.label}
    </span>
  );
}

function SummaryCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || "var(--color-text)" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default function COSVariance() {
  const { orgUnitId } = useAuth();
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<number>(orgUnitId);
  const [period, setPeriod] = useState<string>(currentMonth());
  const [dismissingFlag, setDismissingFlag] = useState<CosFlag | null>(null);
  const [dismissReason, setDismissReason] = useState("");

  useEffect(() => { setSiteId(orgUnitId); }, [orgUnitId]);

  const { data, isLoading, isError } = useQuery<CosVarianceData>({
    queryKey: ["cos-variance", siteId, period],
    queryFn: () => api.get(`/cos/variance?org_unit_id=${siteId}&period=${period}`).then(r => r.data),
    enabled: !!siteId && !!period,
  });

  const dismissMutation = useMutation({
    mutationFn: ({ flagId, reason }: { flagId: number; reason: string }) =>
      api.post(`/cos/flags/${flagId}/dismiss`, { reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cos-variance", siteId, period] });
      setDismissingFlag(null);
      setDismissReason("");
    },
  });

  const summary = data?.summary;
  const flags = data?.flags ?? [];
  const variance = summary?.variance_pct;
  const varianceColor = variance == null ? undefined : variance > 0 ? "#dc2626" : "#16a34a";
  const varianceLabel = variance == null
    ? "—"
    : `${variance > 0 ? "+" : ""}${variance.toFixed(1)} pp`;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>COS &amp; Variance</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            Actual vs theoretical cost of sales, with flagged stock variances.
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <SiteSelector value={siteId} onChange={setSiteId} />
          <input
            type="month"
            value={period}
            onChange={e => setPeriod(e.target.value)}
            style={{
              padding: "8px 10px", fontSize: 13,
              border: "1px solid var(--color-border)", borderRadius: 6,
              background: "var(--color-surface)", color: "var(--color-text)",
            }}
          />
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: 24, color: "var(--color-text-muted)" }}>Loading...</div>
      ) : isError || !summary ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)", fontSize: 14 }}>
          No COS data available for this site and period.
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 24 }}>
            <SummaryCard
              label="Actual COS"
              value={formatPct(summary.actual_cos_pct)}
              sub={`Usage: ${formatZAR(summary.actual_usage_value)}`}
            />
            <SummaryCard
              label="Theoretical COS"
              value={formatPct(summary.theoretical_cos_pct)}
              sub={`Usage: ${formatZAR(summary.theoretical_usage_value)}`}
            />
            <SummaryCard label="Variance" value={varianceLabel} color={varianceColor} />
          </div>

          {/* Flagged items table */}
          <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)", fontWeight: 600, fontSize: 14 }}>
              Flagged Items ({flags.length})
            </div>
            {flags.length === 0 ? (
              <div style={{ padding: 24, color: "var(--color-text-muted)", fontSize: 13 }}>
                No variance flags for this period.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--color-border)", color: "var(--color-text-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                      <th style={{ textAlign: "left", padding: "10px 20px" }}>Item</th>
                      <th style={{ textAlign: "right", padding: "10px 12px" }}>Actual Qty</th>
                      <th style={{ textAlign: "right", padding: "10px 12px" }}>Theoretical Qty</th>
                      <th style={{ textAlign: "right", padding: "10px 12px" }}>Variance Qty</th>
                      <th style={{ textAlign: "right", padding: "10px 12px" }}>Variance Value</th>
                      <th style={{ textAlign: "left", padding: "10px 12px" }}>Cause</th>
                      <th style={{ textAlign: "right", padding: "10px 20px" }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {flags.map(flag => (
                      <tr key={flag.id} style={{ borderBottom: "1px solid var(--color-border)", opacity: flag.status === "dismissed" ? 0.5 : 1 }}>
                        <td style={{ padding: "10px 20px", fontWeight: 500 }}>{flag.item_name}</td>
                        <td style={{ padding: "10px 12px", textAlign: "right" }}>{formatQty(flag.actual_qty)}</td>
                        <td style={{ padding: "10px 12px", textAlign: "right" }}>{formatQty(flag.theoretical_qty)}</td>
                        <td style={{ padding: "10px 12px", textAlign: "right", color: (flag.variance_qty ?? 0) < 0 ? "#dc2626" : "var(--color-text)" }}>
                          {formatQty(flag.variance_qty)}
                        </td>
                        <td style={{ padding: "10px 12px", textAlign: "right", color: (flag.variance_value ?? 0) < 0 ? "#dc2626" : "var(--color-text)" }}>
                          {formatZAR(flag.variance_value)}
                        </td>
                        <td style={{ padding: "10px 12px" }}><CauseBadge cause={flag.cause} /></td>
                        <td style={{ padding: "10px 20px", textAlign: "right" }}>
                          {flag.status === "open" ? (
                            <button
                              className="secondary"
                              style={{ fontSize: 12, padding: "4px 12px" }}
                              onClick={() => setDismissingFlag(flag)}
                            >
                              Dismiss
                            </button>
                          ) : (
                            <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Dismissed</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* Dismiss modal */}
      {dismissingFlag && (
        <Modal title={`Dismiss Flag — ${dismissingFlag.item_name}`} onClose={() => setDismissingFlag(null)}>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
            Provide a reason for dismissing this variance flag.
          </p>
          <Field label="Reason">
            <textarea
              rows={3}
              value={dismissReason}
              onChange={e => setDismissReason(e.target.value)}
              autoFocus
              style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, resize: "vertical", font: "inherit" }}
            />
          </Field>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              disabled={!dismissReason.trim() || dismissMutation.isPending}
              onClick={() => dismissMutation.mutate({ flagId: dismissingFlag.id, reason: dismissReason.trim() })}
            >
              {dismissMutation.isPending ? "Saving..." : "Confirm Dismiss"}
            </button>
            <button className="secondary" onClick={() => setDismissingFlag(null)}>Cancel</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
      <div className="card" style={{ width: 440, padding: 28 }} onClick={e => e.stopPropagation()}>
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
