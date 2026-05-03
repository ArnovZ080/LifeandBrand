import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";
import type { PurchaseOrder, Delivery, StockTake } from "../types";

export default function Dashboard() {
  const { data: pos = [] } = useQuery<PurchaseOrder[]>({
    queryKey: ["purchase-orders"],
    queryFn: () => api.get("/purchase-orders/").then((r) => r.data),
  });
  const { data: deliveries = [] } = useQuery<Delivery[]>({
    queryKey: ["deliveries"],
    queryFn: () => api.get("/deliveries/").then((r) => r.data),
  });
  const { data: stockTakes = [] } = useQuery<StockTake[]>({
    queryKey: ["stock-takes"],
    queryFn: () => api.get("/stock-takes/").then((r) => r.data),
  });

  const openPOs = pos.filter((p) => p.status === "draft" || p.status === "sent").length;
  const pendingDeliveries = deliveries.filter((d) => d.status === "pending").length;
  const recentTake = stockTakes[0];

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}>Stock Control Dashboard</h1>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 32 }}>
        <StatCard label="Open Purchase Orders" value={openPOs} color="blue" />
        <StatCard label="Deliveries Awaiting Check-in" value={pendingDeliveries} color="yellow" />
        <StatCard
          label="Last Stock Take"
          value={recentTake ? recentTake.take_date : "—"}
          color={recentTake?.is_finalised ? "green" : "gray"}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div className="card">
          <h3 style={{ fontWeight: 600, marginBottom: 12 }}>Recent Purchase Orders</h3>
          {pos.slice(0, 5).length === 0 ? (
            <p style={{ color: "var(--color-text-muted)" }}>No purchase orders yet.</p>
          ) : (
            <table>
              <thead>
                <tr><th>PO Number</th><th>Date</th><th>Status</th></tr>
              </thead>
              <tbody>
                {pos.slice(0, 5).map((po) => (
                  <tr key={po.id}>
                    <td>{po.po_number}</td>
                    <td>{po.order_date}</td>
                    <td><StatusBadge status={po.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3 style={{ fontWeight: 600, marginBottom: 12 }}>Recent Deliveries</h3>
          {deliveries.slice(0, 5).length === 0 ? (
            <p style={{ color: "var(--color-text-muted)" }}>No deliveries yet.</p>
          ) : (
            <table>
              <thead>
                <tr><th>GRN</th><th>Date</th><th>Status</th></tr>
              </thead>
              <tbody>
                {deliveries.slice(0, 5).map((d) => (
                  <tr key={d.id}>
                    <td>{d.grn_number}</td>
                    <td>{d.delivery_date}</td>
                    <td><StatusBadge status={d.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="card" style={{ textAlign: "center" }}>
      <div style={{ fontSize: 32, fontWeight: 700, marginBottom: 6 }}>{value}</div>
      <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>{label}</div>
    </div>
  );
}

const statusColorMap: Record<string, string> = {
  draft: "gray", sent: "blue", partially_received: "yellow", received: "green", cancelled: "red",
  pending: "yellow", verified: "blue", discrepancy: "red", accepted: "green",
};

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${statusColorMap[status] ?? "gray"}`}>{status.replace("_", " ")}</span>;
}
