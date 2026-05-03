import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";
import type { Supplier } from "../types";

export default function Suppliers() {
  const { data: suppliers = [], isLoading } = useQuery<Supplier[]>({
    queryKey: ["suppliers"],
    queryFn: () => api.get("/suppliers/").then((r) => r.data),
  });

  if (isLoading) return <p>Loading...</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Suppliers</h1>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Contact</th>
              <th>Email</th>
              <th>Payment Terms</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {suppliers.length === 0 ? (
              <tr><td colSpan={6} style={{ color: "var(--color-text-muted)", textAlign: "center" }}>No suppliers yet</td></tr>
            ) : suppliers.map((s) => (
              <tr key={s.id}>
                <td><code>{s.code}</code></td>
                <td style={{ fontWeight: 500 }}>{s.name}</td>
                <td>{s.contact_name ?? "—"}</td>
                <td>{s.contact_email ?? "—"}</td>
                <td>{s.payment_terms_days} days</td>
                <td>
                  <span className={`badge ${s.is_active ? "green" : "gray"}`}>
                    {s.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
