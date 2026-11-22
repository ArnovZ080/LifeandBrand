import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";
import SiteSelector from "../components/SiteSelector";
import { useSiteSelection } from "../hooks/useSiteSelection";

interface Item { id: number; code: string; name: string; unit: string; }
interface Par {
  id: number; org_unit_id: number; item_id: number; item_code: string; item_name: string; unit: string;
  par_qty: number; reorder_point: number; updated_by: string | null; updated_at: string | null;
}

function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

// Returns an error message, or null when the pair is valid.
function validatePar(par: string, reorder: string): string | null {
  const p = Number(par);
  const r = Number(reorder);
  if (par.trim() === "" || !(p > 0)) return "Par must be greater than zero";
  if (reorder.trim() === "" || !(r >= 0)) return "Reorder point cannot be negative";
  if (r >= p) return "Reorder point must be less than par";
  return null;
}

const inputStyle = {
  padding: "8px 10px", fontSize: 13, width: "100%",
  border: "1px solid var(--color-border)", borderRadius: 6,
  background: "var(--color-surface)", color: "var(--color-text)",
} as const;

export default function ParLevels() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [siteId, setSiteId] = useSiteSelection();

  const [newItemId, setNewItemId] = useState<string>("");
  const [newPar, setNewPar] = useState("");
  const [newReorder, setNewReorder] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editPar, setEditPar] = useState("");
  const [editReorder, setEditReorder] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);

  const { data: items = [] } = useQuery<Item[]>({
    queryKey: ["par-items"],
    queryFn: () => api.get("/par-levels/items").then(r => r.data),
  });

  const { data: pars = [], isLoading, isError } = useQuery<Par[]>({
    queryKey: ["par-levels", siteId],
    queryFn: () => api.get(`/par-levels/?org_unit_id=${siteId}`).then(r => r.data),
    enabled: siteId !== null,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["par-levels", siteId] });
    qc.invalidateQueries({ queryKey: ["shopping-list"] });
  };

  const upsert = useMutation({
    mutationFn: (body: { item_id: number; par_qty: number; reorder_point: number }) =>
      api.put("/par-levels/", { org_unit_id: siteId, ...body }).then(r => r.data),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: err => setActionError(errorMessage(err, "Could not save the par level")),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/par-levels/${id}`).then(r => r.data),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: err => setActionError(errorMessage(err, "Could not remove the par level")),
  });

  const takenItemIds = new Set(pars.map(p => p.item_id));
  const availableItems = items.filter(i => !takenItemIds.has(i.id));

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const problem = !newItemId ? "Choose an item" : validatePar(newPar, newReorder);
    if (siteId === null) return;
    if (problem) {
      setFormError(problem);
      return;
    }
    setFormError(null);
    upsert.mutate(
      { item_id: Number(newItemId), par_qty: Number(newPar), reorder_point: Number(newReorder) },
      {
        onSuccess: () => {
          setNewItemId("");
          setNewPar("");
          setNewReorder("");
        },
      },
    );
  }

  function startEdit(p: Par) {
    setEditingId(p.id);
    setEditPar(String(p.par_qty));
    setEditReorder(String(p.reorder_point));
    setEditError(null);
  }

  function saveEdit(p: Par) {
    const problem = validatePar(editPar, editReorder);
    if (problem) {
      setEditError(problem);
      return;
    }
    upsert.mutate(
      { item_id: p.item_id, par_qty: Number(editPar), reorder_point: Number(editReorder) },
      { onSuccess: () => setEditingId(null) },
    );
  }

  function confirmRemove(p: Par) {
    if (window.confirm(`Remove the par for ${p.item_name}? It will stop appearing on the shopping list.`)) {
      remove.mutate(p.id);
    }
  }

  const newProblem = newPar || newReorder ? validatePar(newPar, newReorder) : null;

  return (
    <div style={{ maxWidth: 960 }}>
      <h2 style={{ fontWeight: 600, marginBottom: 4 }}>Par Levels</h2>
      <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginBottom: 20 }}>
        Target stock per item for each site. The shopping list suggests an order when on-hand falls to or below the reorder point.
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 20 }}>
        <SiteSelector value={siteId ?? 0} onChange={setSiteId} />
        {user && <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Signed in as {user.name}</span>}
      </div>

      {actionError && (
        <div style={{ color: "var(--color-danger)", fontSize: 13, marginBottom: 12 }}>{actionError}</div>
      )}

      <div className="card" style={{ marginBottom: 20 }}>
        <h3 style={{ fontWeight: 600, fontSize: 15, marginBottom: 12 }}>Add an item</h3>
        <form onSubmit={handleAdd} style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", alignItems: "end" }}>
          <div>
            <label style={{ display: "block", fontWeight: 500, fontSize: 13, marginBottom: 4 }}>Item</label>
            <select style={inputStyle} value={newItemId} onChange={e => setNewItemId(e.target.value)}>
              <option value="">Choose an item</option>
              {availableItems.map(i => (
                <option key={i.id} value={i.id}>{i.name} ({i.unit})</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontWeight: 500, fontSize: 13, marginBottom: 4 }}>Par</label>
            <input style={inputStyle} type="number" min="0" step="any" inputMode="decimal" value={newPar} onChange={e => setNewPar(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", fontWeight: 500, fontSize: 13, marginBottom: 4 }}>Reorder point</label>
            <input style={inputStyle} type="number" min="0" step="any" inputMode="decimal" value={newReorder} onChange={e => setNewReorder(e.target.value)} />
          </div>
          <div>
            <button type="submit" disabled={upsert.isPending}>Add</button>
          </div>
        </form>
        {(formError || newProblem) && (
          <div style={{ color: "var(--color-danger)", fontSize: 12, marginTop: 8 }}>{formError ?? newProblem}</div>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {isLoading && <div style={{ padding: 20, color: "var(--color-text-muted)" }}>Loading...</div>}
        {isError && <div style={{ padding: 20, color: "var(--color-danger)" }}>Could not load par levels for this site.</div>}
        {!isLoading && !isError && pars.length === 0 && (
          <div style={{ padding: 20, color: "var(--color-text-muted)" }}>No par levels set for this site yet.</div>
        )}
        {pars.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Par</th>
                <th>Reorder point</th>
                <th>Updated by</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pars.map(p => {
                const editing = editingId === p.id;
                return (
                  <tr key={p.id}>
                    <td>{p.item_name} <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>({p.unit})</span></td>
                    <td style={{ width: 130 }}>
                      {editing
                        ? <input style={inputStyle} type="number" min="0" step="any" value={editPar} onChange={e => setEditPar(e.target.value)} />
                        : p.par_qty}
                    </td>
                    <td style={{ width: 150 }}>
                      {editing
                        ? <input style={inputStyle} type="number" min="0" step="any" value={editReorder} onChange={e => setEditReorder(e.target.value)} />
                        : p.reorder_point}
                    </td>
                    <td style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{p.updated_by ?? "-"}</td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      {editing ? (
                        <>
                          <button onClick={() => saveEdit(p)} disabled={upsert.isPending}>Save</button>{" "}
                          <button className="secondary" onClick={() => setEditingId(null)}>Cancel</button>
                          {editError && <div style={{ color: "var(--color-danger)", fontSize: 12, marginTop: 6 }}>{editError}</div>}
                        </>
                      ) : (
                        <>
                          <button className="secondary" onClick={() => startEdit(p)}>Edit</button>{" "}
                          <button className="danger" onClick={() => confirmRemove(p)} disabled={remove.isPending}>Remove</button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
