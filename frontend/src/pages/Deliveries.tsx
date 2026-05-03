import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";
import type { Delivery } from "../types";

const statusColor: Record<string, string> = {
  pending: "yellow", verified: "blue", discrepancy: "red", accepted: "green",
};

export default function Deliveries() {
  const { data: deliveries = [], isLoading } = useQuery<Delivery[]>({
    queryKey: ["deliveries"],
    queryFn: () => api.get("/deliveries/").then((r) => r.data),
  });

  if (isLoading) return <p>Loading...</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Deliveries (GRN)</h1>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>GRN Number</th>
              <th>Date</th>
              <th>Received By</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.length === 0 ? (
              <tr><td colSpan={4} style={{ color: "var(--color-text-muted)", textAlign: "center" }}>No deliveries yet</td></tr>
            ) : deliveries.map((d) => (
              <tr key={d.id}>
                <td style={{ fontWeight: 500 }}>{d.grn_number}</td>
                <td>{d.delivery_date}</td>
                <td>{d.received_by ?? "—"}</td>
                <td><span className={`badge ${statusColor[d.status]}`}>{d.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
