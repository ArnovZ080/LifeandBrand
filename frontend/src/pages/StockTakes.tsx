import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";
import type { StockTake, VarianceItem } from "../types";

export default function StockTakes() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: takes = [], isLoading } = useQuery<StockTake[]>({
    queryKey: ["stock-takes"],
    queryFn: () => api.get("/stock-takes/").then((r) => r.data),
  });

  const { data: variance = [] } = useQuery<VarianceItem[]>({
    queryKey: ["variance", selectedId],
    queryFn: () => api.get(`/stock-takes/${selectedId}/variance`).then((r) => r.data),
    enabled: selectedId !== null && takes.find((t) => t.id === selectedId)?.is_finalised === true,
  });

  const finaliseMutation = useMutation({
    mutationFn: (id: number) => api.post(`/stock-takes/${id}/finalise`).then((r) => r.data),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["stock-takes"] });
      setSelectedId(id);
    },
  });

  if (isLoading) return <p>Loading...</p>;

  const selected = takes.find((t) => t.id === selectedId);

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>Stock Takes & Variance</h1>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 20 }}>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--color-border)", fontWeight: 600, fontSize: 13 }}>
            Stock Takes
          </div>
          {takes.length === 0 ? (
            <p style={{ padding: 16, color: "var(--color-text-muted)" }}>No stock takes yet</p>
          ) : takes.map((t) => (
            <div
              key={t.id}
              onClick={() => setSelectedId(t.id)}
              style={{
                padding: "12px 16px",
                cursor: "pointer",
                background: selectedId === t.id ? "#f0f4ff" : "transparent",
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              <div style={{ fontWeight: 500 }}>{t.take_date}</div>
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <span className={`badge ${t.is_finalised ? "green" : "yellow"}`}>
                  {t.is_finalised ? "Finalised" : "Draft"}
                </span>
              </div>
            </div>
          ))}
        </div>

        <div>
          {!selected ? (
            <div className="card" style={{ color: "var(--color-text-muted)" }}>
              Select a stock take to view variance report
            </div>
          ) : (
            <div>
              <div className="card" style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>Stock Take: {selected.take_date}</div>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
                    {selected.is_finalised ? "Finalised — variance report below" : "Draft — finalise to calculate variance"}
                  </div>
                </div>
                {!selected.is_finalised && (
                  <button
                    onClick={() => finaliseMutation.mutate(selected.id)}
                    disabled={finaliseMutation.isPending}
                  >
                    {finaliseMutation.isPending ? "Calculating..." : "Finalise & Calculate Variance"}
                  </button>
                )}
              </div>

              {selected.is_finalised && variance.length > 0 && (
                <VarianceTable items={variance} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function VarianceTable({ items }: { items: VarianceItem[] }) {
  const totalVarianceValue = items.reduce((sum, i) => sum + i.variance_value, 0);

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
        <h3 style={{ fontWeight: 600 }}>Variance Report</h3>
        <div style={{ fontWeight: 700, fontSize: 15, color: totalVarianceValue < 0 ? "var(--color-danger)" : "var(--color-success)" }}>
          Total: {totalVarianceValue < 0 ? "-" : "+"}R{Math.abs(totalVarianceValue).toFixed(2)}
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Opening</th>
            <th>In</th>
            <th>Theoretical Usage</th>
            <th>Theoretical Close</th>
            <th>Actual Count</th>
            <th>Variance Qty</th>
            <th>Variance Value</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.item_id}>
              <td>
                <div style={{ fontWeight: 500 }}>{item.item_name}</div>
                <div style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{item.item_code}</div>
              </td>
              <td>{item.opening_stock.toFixed(2)}</td>
              <td>{item.stock_in.toFixed(2)}</td>
              <td>{item.theoretical_usage.toFixed(2)}</td>
              <td>{item.theoretical_closing.toFixed(2)}</td>
              <td style={{ fontWeight: 500 }}>{item.actual_closing.toFixed(2)}</td>
              <td className={item.variance_quantity < 0 ? "variance-negative" : "variance-positive"}>
                {item.variance_quantity > 0 ? "+" : ""}{item.variance_quantity.toFixed(2)}
              </td>
              <td className={item.variance_value < 0 ? "variance-negative" : "variance-positive"}>
                {item.variance_value > 0 ? "+" : ""}R{item.variance_value.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
