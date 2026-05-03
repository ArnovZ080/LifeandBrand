import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";
import type { PurchaseOrder } from "../types";

const statusColor: Record<string, string> = {
  draft: "gray", sent: "blue", partially_received: "yellow", received: "green", cancelled: "red",
};

export default function PurchaseOrders() {
  const { data: pos = [], isLoading } = useQuery<PurchaseOrder[]>({
    queryKey: ["purchase-orders"],
    queryFn: () => api.get("/purchase-orders/").then((r) => r.data),
  });

  if (isLoading) return <p>Loading...</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Purchase Orders</h1>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>PO Number</th>
              <th>Order Date</th>
              <th>Expected Delivery</th>
              <th>Lines</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {pos.length === 0 ? (
              <tr><td colSpan={5} style={{ color: "var(--color-text-muted)", textAlign: "center" }}>No purchase orders yet</td></tr>
            ) : pos.map((po) => (
              <tr key={po.id}>
                <td style={{ fontWeight: 500 }}>{po.po_number}</td>
                <td>{po.order_date}</td>
                <td>{po.expected_delivery_date ?? "—"}</td>
                <td>{po.lines.length}</td>
                <td><span className={`badge ${statusColor[po.status]}`}>{po.status.replace(/_/g, " ")}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
