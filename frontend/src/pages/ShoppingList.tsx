import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../hooks/useApi";
import SiteSelector from "../components/SiteSelector";
import { useSiteSelection } from "../hooks/useSiteSelection";

interface Line {
  item_id: number; item_name: string; unit: string;
  on_hand_qty: number; on_order_qty: number; par_qty: number; reorder_point: number; order_qty: number;
  estimated_unit_price: number | null; estimated_value: number | null;
}
interface Group { supplier_id: number; supplier_name: string; lines: Line[]; total_estimated_value: number; }
interface ShoppingListData { org_unit_id: number; generated_at: string; groups: Group[]; unassigned: Line[]; }
interface DraftsResult { requisitions: { id: number; requisition_number: string; supplier_id: number | null; status: string; line_count: number }[]; }

function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

const qty = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 3 });
const money = (n: number | null) =>
  n === null ? "No price" : n.toLocaleString(undefined, { style: "currency", currency: "ZAR" });

const th: React.CSSProperties = { textAlign: "right" };
const td: React.CSSProperties = { textAlign: "right" };

function LinesTable({ lines, showValue = true }: { lines: Line[]; showValue?: boolean }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th style={th}>On hand</th>
            <th style={th}>On order</th>
            <th style={th}>Par</th>
            <th style={th}>Order</th>
            {showValue && <th style={th}>Est. value</th>}
          </tr>
        </thead>
        <tbody>
          {lines.map(l => (
            <tr key={l.item_id}>
              <td>{l.item_name} <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>({l.unit})</span></td>
              <td style={td}>{qty(l.on_hand_qty)}</td>
              <td style={td}>{qty(l.on_order_qty)}</td>
              <td style={td}>{qty(l.par_qty)}</td>
              <td style={{ ...td, fontWeight: 600 }}>{qty(l.order_qty)}</td>
              {showValue && <td style={td}>{money(l.estimated_value)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ShoppingList() {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useSiteSelection();
  const [confirming, setConfirming] = useState(false);
  const [created, setCreated] = useState<DraftsResult["requisitions"] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<ShoppingListData>({
    queryKey: ["shopping-list", siteId],
    queryFn: () => api.get(`/shopping-list/?org_unit_id=${siteId}`).then(r => r.data),
    enabled: siteId !== null,
  });

  const createDrafts = useMutation({
    mutationFn: () => api.post("/shopping-list/create-drafts", { org_unit_id: siteId }).then(r => r.data as DraftsResult),
    onSuccess: result => {
      setCreated(result.requisitions);
      setConfirming(false);
      setActionError(null);
      qc.invalidateQueries({ queryKey: ["shopping-list", siteId] });
    },
    onError: err => {
      setConfirming(false);
      setActionError(errorMessage(err, "Could not create draft requisitions"));
    },
  });

  const groups = data?.groups ?? [];
  const unassigned = data?.unassigned ?? [];
  const isEmpty = !isLoading && !isError && groups.length === 0 && unassigned.length === 0;
  const orderable = groups.length > 0;
  const grandTotal = groups.reduce((sum, g) => sum + g.total_estimated_value, 0);

  return (
    <div style={{ maxWidth: 960 }}>
      <h2 style={{ fontWeight: 600, marginBottom: 4 }}>Shopping List</h2>
      <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginBottom: 20 }}>
        Items at or below their reorder point, with the quantity needed to get back to par, rounded up to pack size and grouped by supplier.
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 20 }}>
        <SiteSelector value={siteId ?? 0} onChange={id => { setSiteId(id); setCreated(null); setConfirming(false); }} />
        {data && (
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Generated {new Date(data.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {isLoading && <div style={{ color: "var(--color-text-muted)" }}>Loading...</div>}
      {isError && <div style={{ color: "var(--color-danger)" }}>Could not load the shopping list for this site.</div>}

      {isEmpty && (
        <div className="card" style={{ textAlign: "center", padding: 32, color: "var(--color-text-muted)" }}>
          Nothing below reorder point.
        </div>
      )}

      {created && (
        <div className="card" style={{ marginBottom: 20, borderColor: "var(--color-success)" }}>
          <strong style={{ color: "var(--color-success)" }}>
            {created.length} draft requisition{created.length === 1 ? "" : "s"} created
          </strong>
          <ul style={{ margin: "8px 0 0 18px", fontSize: 13 }}>
            {created.map(r => (
              <li key={r.id}>{r.requisition_number} ({r.line_count} line{r.line_count === 1 ? "" : "s"})</li>
            ))}
          </ul>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 8 }}>
            These are drafts. Nothing has been submitted; they go through approval when submitted.
          </p>
        </div>
      )}

      {actionError && <div style={{ color: "var(--color-danger)", fontSize: 13, marginBottom: 12 }}>{actionError}</div>}

      {groups.map(g => (
        <div className="card" key={g.supplier_id} style={{ marginBottom: 16, padding: 0 }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--color-border)", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <strong>{g.supplier_name}</strong>
            <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Estimated {money(g.total_estimated_value)}</span>
          </div>
          <LinesTable lines={g.lines} />
        </div>
      ))}

      {unassigned.length > 0 && (
        <div className="card" style={{ marginBottom: 16, padding: 0, borderColor: "var(--color-warning)" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--color-border)" }}>
            <strong>No preferred supplier</strong>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 4 }}>
              These items are below reorder point but have no preferred supplier, so they are not ordered. Assign a preferred supplier to include them.
            </div>
          </div>
          <LinesTable lines={unassigned} showValue={false} />
        </div>
      )}

      {orderable && (
        <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 14 }}>
            Total estimated <strong>{money(grandTotal)}</strong> across {groups.length} supplier{groups.length === 1 ? "" : "s"}
          </div>
          {!confirming ? (
            <button onClick={() => { setConfirming(true); setCreated(null); }} disabled={createDrafts.isPending}>
              Create draft requisitions
            </button>
          ) : (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: 13 }}>
                Create {groups.length} draft requisition{groups.length === 1 ? "" : "s"}? Drafts are not submitted.
              </span>
              <button onClick={() => createDrafts.mutate()} disabled={createDrafts.isPending}>
                {createDrafts.isPending ? "Creating..." : "Confirm"}
              </button>
              <button className="secondary" onClick={() => setConfirming(false)} disabled={createDrafts.isPending}>
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
