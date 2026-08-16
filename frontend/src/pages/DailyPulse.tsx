import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";
import SiteSelector from "../components/SiteSelector";

interface Comparators {
  vs_last_year_pct: number | null;
  vs_budget_pct: number | null;
  vs_prior_month_pct: number | null;
  portfolio_share_pct: number | null;
}

interface DailyPulseData {
  org_unit_id: number;
  business_date: string | null;
  mtd_net_sales: number | null;
  comparators: Comparators | null;
  projection_month_end: number | null;
  covers_mtd: number | null;
  spend_per_head: number | null;
  ledger_status: "green" | "red" | "pending" | null;
}

function formatZAR(value: number | null | undefined): string {
  if (value == null) return "—";
  return "R " + Math.round(value).toLocaleString("en-ZA").replace(/,/g, " ");
}

function formatSignedPct(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function ComparatorCard({ label, value, neutral = false }: { label: string; value: number | null | undefined; neutral?: boolean }) {
  const color = neutral || value == null
    ? "var(--color-text)"
    : value >= 0 ? "#16a34a" : "#dc2626";
  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {neutral && value != null ? `${value.toFixed(1)}%` : formatSignedPct(value)}
      </div>
    </div>
  );
}

function LedgerBadge({ status }: { status: DailyPulseData["ledger_status"] }) {
  const cfg = status === "green"
    ? { dot: "#16a34a", label: "Verified", bg: "#f0fdf4", border: "#bbf7d0" }
    : status === "red"
      ? { dot: "#dc2626", label: "Accuracy issue", bg: "#fef2f2", border: "#fecaca" }
      : { dot: "#9ca3af", label: "Pending verification", bg: "#f9fafb", border: "#e5e7eb" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 999, fontSize: 12,
      background: cfg.bg, border: `1px solid ${cfg.border}`, color: "var(--color-text)",
    }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: cfg.dot, flexShrink: 0 }} />
      {cfg.label}
    </span>
  );
}

export default function DailyPulse() {
  const { orgUnitId } = useAuth();
  const [siteId, setSiteId] = useState<number>(orgUnitId);

  // Keep in sync if the user's active org unit changes (e.g. via sidebar switcher)
  useEffect(() => { setSiteId(orgUnitId); }, [orgUnitId]);

  const { data, isLoading, isError } = useQuery<DailyPulseData>({
    queryKey: ["daily-pulse", siteId],
    queryFn: () => api.get(`/daily-pulse/?org_unit_id=${siteId}`).then(r => r.data),
    enabled: !!siteId,
  });

  const comparators = data?.comparators;
  const hasData = data != null && data.mtd_net_sales != null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Daily Pulse</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            Morning heartbeat — month-to-date sales performance
            {data?.business_date ? ` as of ${data.business_date}` : ""}.
          </p>
        </div>
        <SiteSelector value={siteId} onChange={setSiteId} />
      </div>

      {isLoading ? (
        <div style={{ padding: 24, color: "var(--color-text-muted)" }}>Loading...</div>
      ) : isError || !hasData ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)", fontSize: 14 }}>
          No sales data ingested yet for this site.
        </div>
      ) : (
        <>
          {/* Big MTD net sales card */}
          <div className="card" style={{ padding: "24px 28px", marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 8 }}>MTD Net Sales</div>
              <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1.1 }}>{formatZAR(data.mtd_net_sales)}</div>
            </div>
            <LedgerBadge status={data.ledger_status ?? "pending"} />
          </div>

          {/* Comparator cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
            <ComparatorCard label="vs Last Year" value={comparators?.vs_last_year_pct} />
            <ComparatorCard label="vs Budget" value={comparators?.vs_budget_pct} />
            <ComparatorCard label="vs Prior Month" value={comparators?.vs_prior_month_pct} />
            <ComparatorCard label="Portfolio Share" value={comparators?.portfolio_share_pct} neutral />
          </div>

          {/* Projection + covers + spend per head */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            <div className="card" style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>Projected Month-End</div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>{formatZAR(data.projection_month_end)}</div>
            </div>
            <div className="card" style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>Covers MTD</div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>
                {data.covers_mtd != null ? data.covers_mtd.toLocaleString("en-ZA").replace(/,/g, " ") : "—"}
              </div>
            </div>
            <div className="card" style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>Spend per Head</div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>{formatZAR(data.spend_per_head)}</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
