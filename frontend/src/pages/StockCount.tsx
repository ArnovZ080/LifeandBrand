import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";
import SiteSelector from "../components/SiteSelector";
import { useSiteSelection } from "../hooks/useSiteSelection";

interface CountSummary {
  id: number; name: string; count_date: string; status: "open" | "submitted"; blind: boolean;
  template_id: number | null; line_count: number; counted_count: number;
}
interface Line {
  id: number; item_id: number; item_name: string;
  system_qty: number | null; counted_qty: number | null;
  variance_qty: number | null; variance_value: number | null;
}
interface Count {
  id: number; name: string; count_date: string; status: "open" | "submitted"; blind: boolean;
  submitted_at: string | null; lines: Line[];
}
interface Template { id: number; name: string; item_ids: number[]; }
interface ParItem { id: number; code: string; name: string; unit: string; }
interface SubmitResult { name: string; counted: number; withVariance: number; totalVariance: number; }

type Screen = { name: "home" } | { name: "new" } | { name: "count"; id: number };

const muted = { color: "var(--color-text-muted)", fontSize: 13 } as const;

const fieldStyle: CSSProperties = {
  padding: "10px 12px", fontSize: 16, width: "100%", minHeight: 44, boxSizing: "border-box",
  border: "1px solid var(--color-border)", borderRadius: 6,
  background: "var(--color-surface)", color: "var(--color-text)",
};

const bigInputStyle: CSSProperties = {
  ...fieldStyle, fontSize: 32, fontWeight: 600, textAlign: "center", minHeight: 64,
  fontVariantNumeric: "tabular-nums",
};

const bigButton: CSSProperties = {
  minHeight: 52, width: "100%", fontSize: 16, fontWeight: 600, padding: "12px 14px",
};

const halfButton: CSSProperties = { minHeight: 48, flex: 1, fontSize: 15, padding: "10px 12px" };

function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function todayIso(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function fmtQty(v: number): string {
  return String(Math.round(v * 10000) / 10000);
}

function fmtMoney(v: number): string {
  return `${v < 0 ? "-" : ""}${Math.abs(v).toFixed(2)}`;
}

// Accepts up to four decimal places and a comma as the decimal mark.
function parseQty(raw: string): number | null {
  const s = raw.trim().replace(",", ".");
  if (!/^\d+(\.\d{1,4})?$/.test(s)) return null;
  return Number(s);
}

function firstOpenIndex(lines: Line[]): number {
  const i = lines.findIndex(l => l.counted_qty == null);
  return i >= 0 ? i : 0;
}

function summarise(count: Count): SubmitResult {
  return {
    name: count.name,
    counted: count.lines.length,
    withVariance: count.lines.filter(l => (l.variance_qty ?? 0) !== 0).length,
    totalVariance: count.lines.reduce((sum, l) => sum + (l.variance_value ?? 0), 0),
  };
}

export default function StockCount() {
  const [siteId, setSiteId] = useSiteSelection();
  const [screen, setScreen] = useState<Screen>({ name: "home" });
  const [result, setResult] = useState<SubmitResult | null>(null);

  return (
    <div style={{ maxWidth: 480, margin: "0 auto", padding: "0 16px", boxSizing: "border-box", width: "100%" }}>
      <h2 style={{ fontWeight: 600, marginBottom: 4 }}>Stock Count</h2>
      <p style={{ ...muted, marginBottom: 16 }}>Count a site's stock item by item, in shelf order.</p>

      <div style={{ marginBottom: 16 }}>
        <SiteSelector value={siteId ?? 0} onChange={setSiteId} />
      </div>

      {siteId === null && (
        <div className="card" style={muted}>
          No site selected. If the list is empty, your account has no sites.
        </div>
      )}

      {siteId !== null && screen.name === "home" && (
        <HomeView
          siteId={siteId}
          result={result}
          onDismissResult={() => setResult(null)}
          onNew={() => setScreen({ name: "new" })}
          onOpen={id => setScreen({ name: "count", id })}
        />
      )}

      {siteId !== null && screen.name === "new" && (
        <NewCountView
          siteId={siteId}
          onCancel={() => setScreen({ name: "home" })}
          onCreated={id => setScreen({ name: "count", id })}
        />
      )}

      {screen.name === "count" && (
        <CountView
          key={screen.id}
          countId={screen.id}
          onBack={() => setScreen({ name: "home" })}
          onSubmitted={r => {
            setResult(r);
            setScreen({ name: "home" });
          }}
        />
      )}
    </div>
  );
}

// ── Home: this site's counts ──────────────────────────────────────────────────

function HomeView({ siteId, result, onDismissResult, onNew, onOpen }: {
  siteId: number;
  result: SubmitResult | null;
  onDismissResult: () => void;
  onNew: () => void;
  onOpen: (id: number) => void;
}) {
  const { data: counts = [], isLoading, isError } = useQuery<CountSummary[]>({
    queryKey: ["stock-counts", siteId],
    queryFn: () => api.get(`/stock-counts/?org_unit_id=${siteId}`).then(r => r.data),
  });

  return (
    <>
      {result && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--color-success)" }}>
          <div style={{ fontWeight: 600 }}>{result.name} submitted</div>
          <div style={{ ...muted, marginTop: 4 }}>
            {result.counted} lines counted, {result.withVariance} with a variance
          </div>
          <div style={{ marginTop: 4 }}>Total variance value: {fmtMoney(result.totalVariance)}</div>
          <button className="secondary" onClick={onDismissResult} style={{ marginTop: 10, minHeight: 40 }}>
            Dismiss
          </button>
        </div>
      )}

      <button onClick={onNew} style={bigButton}>Start count</button>

      <div className="card" style={{ marginTop: 16, padding: 0, overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 16, ...muted }}>Loading counts...</div>}
        {isError && (
          <div style={{ padding: 16, color: "var(--color-danger)" }}>Could not load counts for this site.</div>
        )}
        {!isLoading && !isError && counts.length === 0 && (
          <div style={{ padding: 16, ...muted }}>No counts yet for this site. Tap Start count to begin one.</div>
        )}
        {counts.map((c, i) => (
          <button
            key={c.id}
            className="secondary"
            onClick={() => onOpen(c.id)}
            style={{
              display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center",
              gap: 12, textAlign: "left", padding: "14px 16px", minHeight: 60, borderRadius: 0,
              border: "none", borderBottom: i < counts.length - 1 ? "1px solid var(--color-border)" : "none",
              background: "var(--color-surface)",
            }}
          >
            <span style={{ minWidth: 0 }}>
              <span style={{ display: "block", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {c.name}
              </span>
              <span style={{ display: "block", ...muted }}>
                {c.count_date}{c.blind ? " · Blind" : ""}
              </span>
            </span>
            <span style={{ textAlign: "right", whiteSpace: "nowrap", flexShrink: 0 }}>
              <span className={`badge ${c.status === "submitted" ? "green" : "yellow"}`}>{c.status}</span>
              <span style={{ display: "block", ...muted }}>{c.counted_count} / {c.line_count} counted</span>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

// ── New count ─────────────────────────────────────────────────────────────────

function NewCountView({ siteId, onCancel, onCreated }: {
  siteId: number;
  onCancel: () => void;
  onCreated: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState(`Count ${todayIso()}`);
  const [blind, setBlind] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: templates = [] } = useQuery<Template[]>({
    queryKey: ["stock-count-templates", siteId],
    queryFn: () => api.get(`/stock-counts/templates?org_unit_id=${siteId}`).then(r => r.data),
  });
  const { data: parItems = [], isLoading: itemsLoading, isError: itemsError } = useQuery<ParItem[]>({
    queryKey: ["par-items"],
    queryFn: () => api.get("/par-levels/items").then(r => r.data),
  });

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Count>("/stock-counts/", body).then(r => r.data),
    onSuccess: count => {
      qc.invalidateQueries({ queryKey: ["stock-counts"] });
      onCreated(count.id);
    },
    onError: err => setError(errorMessage(err, "Could not start the count. Try again.")),
  });

  const selectedTemplate = templates.find(t => String(t.id) === templateId);
  const itemTotal = selectedTemplate ? selectedTemplate.item_ids.length : parItems.length;

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Give the count a name");
      return;
    }
    const base = { org_unit_id: siteId, name: name.trim(), blind };
    if (selectedTemplate) {
      create.mutate({ ...base, template_id: selectedTemplate.id });
      return;
    }
    if (itemsLoading) {
      setError("Items are still loading. Try again in a moment.");
      return;
    }
    if (itemsError || parItems.length === 0) {
      setError("There are no active items to count.");
      return;
    }
    create.mutate({ ...base, item_ids: parItems.map(i => i.id) });
  }

  return (
    <form className="card" onSubmit={handleCreate}>
      <h3 style={{ fontWeight: 600, fontSize: 16, marginBottom: 16 }}>Start a count</h3>

      <label htmlFor="count-template" style={{ display: "block", fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
        Template
      </label>
      <select
        id="count-template"
        style={fieldStyle}
        value={templateId}
        onChange={e => { setTemplateId(e.target.value); setError(null); }}
      >
        <option value="">All active items</option>
        {templates.map(t => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
      <div style={{ ...muted, marginTop: 4 }}>{itemTotal} items</div>

      <label htmlFor="count-name" style={{ display: "block", fontWeight: 600, fontSize: 13, marginTop: 16, marginBottom: 6 }}>
        Name
      </label>
      <input
        id="count-name"
        type="text"
        style={fieldStyle}
        value={name}
        maxLength={120}
        onChange={e => { setName(e.target.value); setError(null); }}
      />

      <label style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16, minHeight: 44, fontSize: 15 }}>
        <input
          type="checkbox"
          checked={blind}
          onChange={e => setBlind(e.target.checked)}
          style={{ width: 20, height: 20 }}
        />
        Blind count (hide expected quantities until submitted)
      </label>

      {error && <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13, marginTop: 12 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
        <button type="button" className="secondary" onClick={onCancel} style={halfButton}>Cancel</button>
        <button type="submit" disabled={create.isPending} style={halfButton}>
          {create.isPending ? "Starting..." : "Start count"}
        </button>
      </div>
    </form>
  );
}

// ── Count: item by item ───────────────────────────────────────────────────────

function CountView({ countId, onBack, onSubmitted }: {
  countId: number;
  onBack: () => void;
  onSubmitted: (r: SubmitResult) => void;
}) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const counterName = user?.name || "Counter";

  const { data: count, isLoading, isError } = useQuery<Count>({
    queryKey: ["stock-count", countId],
    queryFn: () => api.get(`/stock-counts/${countId}`).then(r => r.data),
  });
  const { data: parItems = [] } = useQuery<ParItem[]>({
    queryKey: ["par-items"],
    queryFn: () => api.get("/par-levels/items").then(r => r.data),
  });
  const unitById = useMemo(() => new Map(parItems.map(i => [i.id, i.unit])), [parItems]);

  const [index, setIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [lastSaved, setLastSaved] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const lines = count?.lines ?? [];

  // Start at the first uncounted item once the count has loaded.
  useEffect(() => {
    if (count && index === null) setIndex(firstOpenIndex(count.lines));
  }, [count, index]);

  const idx = Math.min(index ?? 0, Math.max(lines.length - 1, 0));
  const line = lines[idx];
  const counted = lines.filter(l => l.counted_qty != null).length;
  const isOpen = count?.status === "open";
  const savedText = line?.counted_qty != null ? String(line.counted_qty) : "";
  const dirty = !!line && draft.trim() !== savedText;
  const allCounted = isOpen && lines.length > 0 && counted === lines.length;

  // Reset the typed value only when a different item comes on screen.
  useEffect(() => {
    setDraft(line?.counted_qty != null ? String(line.counted_qty) : "");
    setMessage(null);
  }, [line?.id]);

  const save = useMutation({
    mutationFn: (args: { line: Line; qty: number }) =>
      api.put<Count>(`/stock-counts/${countId}/lines`, [
        { item_id: args.line.item_id, counted_qty: args.qty, counted_by: counterName },
      ]).then(r => r.data),
    onMutate: () => {
      setSaveState("saving");
      setMessage(null);
    },
    onSuccess: (data, args) => {
      qc.setQueryData(["stock-count", countId], data);
      qc.invalidateQueries({ queryKey: ["stock-counts"] });
      setLastSaved(args.line.item_name);
      setSaveState("saved");
    },
    onError: err => {
      setSaveState("error");
      setMessage(errorMessage(err, "Could not save this item. Check the connection and try again."));
    },
  });

  const submit = useMutation({
    mutationFn: () => api.post<Count>(`/stock-counts/${countId}/submit`).then(r => r.data),
    onSuccess: data => {
      qc.setQueryData(["stock-count", countId], data);
      qc.invalidateQueries({ queryKey: ["stock-counts"] });
      onSubmitted(summarise(data));
    },
    onError: err => setSubmitError(errorMessage(err, "Could not submit the count. Check that every item is counted.")),
  });

  function moveTo(next: number) {
    if (dirty && !window.confirm("Leave this item? The number you typed has not been saved.")) return;
    setIndex(next);
  }

  function saveLine(advance: boolean) {
    if (!line || !isOpen) return;
    const qty = parseQty(draft);
    if (qty === null) {
      setMessage("Enter a number zero or more, with up to 4 decimal places.");
      return;
    }
    save.mutate({ line, qty }, {
      onSuccess: () => {
        if (advance && idx < lines.length - 1) setIndex(idx + 1);
      },
    });
  }

  if (isLoading) return <div className="card" style={muted}>Loading count...</div>;
  if (isError || !count) {
    return (
      <div className="card">
        <div style={{ color: "var(--color-danger)", marginBottom: 12 }}>Could not load this count.</div>
        <button className="secondary" onClick={onBack} style={{ minHeight: 44 }}>Back to counts</button>
      </div>
    );
  }
  if (!line) {
    return (
      <div className="card">
        <div style={{ marginBottom: 12 }}>This count has no items.</div>
        <button className="secondary" onClick={onBack} style={{ minHeight: 44 }}>Back to counts</button>
      </div>
    );
  }

  const unit = unitById.get(line.item_id) ?? "";
  const progress = lines.length > 0 ? (counted / lines.length) * 100 : 0;

  const header = (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 12 }}>
      <button className="secondary" onClick={onBack} style={{ minHeight: 40 }}>Counts</button>
      <div style={{ textAlign: "right", minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{count.name}</div>
        {count.blind && <span className="badge gray">Blind</span>}
      </div>
    </div>
  );

  const progressBar = (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", ...muted, marginBottom: 4 }}>
        <span>{counted} of {lines.length} counted</span>
        <span>{Math.round(progress)}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={lines.length}
        aria-valuenow={counted}
        style={{ height: 8, background: "var(--color-border)", borderRadius: 4, overflow: "hidden" }}
      >
        <div style={{ width: `${progress}%`, height: "100%", background: "var(--color-success)", transition: "width 0.2s" }} />
      </div>
    </div>
  );

  if (!isOpen) {
    return (
      <>
        {header}
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 600 }}>Submitted</div>
          <div style={muted}>
            {count.submitted_at ? new Date(count.submitted_at).toLocaleDateString() : count.count_date}
          </div>
        </div>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {lines.map((l, i) => (
            <div
              key={l.id}
              style={{
                padding: "12px 16px", borderBottom: i < lines.length - 1 ? "1px solid var(--color-border)" : "none",
              }}
            >
              <div style={{ fontWeight: 600 }}>{l.item_name}</div>
              <div style={muted}>
                Counted {l.counted_qty != null ? fmtQty(l.counted_qty) : "-"} {unitById.get(l.item_id) ?? ""}
                {l.system_qty != null && <> · System {fmtQty(l.system_qty)}</>}
                {l.variance_qty != null && <> · Variance {fmtQty(l.variance_qty)}</>}
              </div>
            </div>
          ))}
        </div>
      </>
    );
  }

  if (confirming) {
    const varianceLines = count.blind
      ? null
      : lines.filter(l => l.system_qty != null && l.counted_qty != null && l.counted_qty !== l.system_qty).length;
    return (
      <>
        {header}
        <div className="card">
          <h3 style={{ fontWeight: 600, fontSize: 16, marginBottom: 8 }}>Submit {count.name}?</h3>
          <div style={{ marginBottom: 8 }}>{counted} of {lines.length} lines counted.</div>
          {varianceLines === null ? (
            <div style={{ ...muted, marginBottom: 12 }}>
              This is a blind count. Variances are hidden until submit, and the total variance value is worked out when you submit.
            </div>
          ) : (
            <div style={{ ...muted, marginBottom: 12 }}>
              {varianceLines} lines with a variance. The total variance value is worked out when you submit.
            </div>
          )}

          <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid var(--color-border)", borderRadius: 6, marginBottom: 16 }}>
            {lines.map((l, i) => (
              <div
                key={l.id}
                style={{
                  display: "flex", justifyContent: "space-between", gap: 8, padding: "10px 12px",
                  borderBottom: i < lines.length - 1 ? "1px solid var(--color-border)" : "none", fontSize: 14,
                }}
              >
                <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{l.item_name}</span>
                <span style={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {l.counted_qty != null ? fmtQty(l.counted_qty) : "-"} {unitById.get(l.item_id) ?? ""}
                </span>
              </div>
            ))}
          </div>

          {submitError && <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13, marginBottom: 12 }}>{submitError}</div>}

          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="secondary" onClick={() => setConfirming(false)} disabled={submit.isPending} style={halfButton}>
              Back to counting
            </button>
            <button type="button" onClick={() => submit.mutate()} disabled={submit.isPending} style={halfButton}>
              {submit.isPending ? "Submitting..." : "Submit count"}
            </button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {header}
      {progressBar}

      <form
        className="card"
        style={{ padding: 20 }}
        onSubmit={e => {
          e.preventDefault();
          saveLine(true);
        }}
      >
        <div style={muted}>{idx + 1} of {lines.length}</div>
        <div style={{ fontSize: 24, fontWeight: 600, lineHeight: 1.2, marginTop: 4, wordBreak: "break-word" }}>
          {line.item_name}
        </div>
        <div style={{ ...muted, marginTop: 4 }}>Unit: {unit || "-"}</div>
        <div style={{ marginTop: 10, fontSize: 15 }}>
          {line.system_qty != null
            ? <>System quantity: <strong>{fmtQty(line.system_qty)}</strong> {unit}</>
            : <span style={muted}>Hidden (blind count)</span>}
        </div>

        <label htmlFor="counted-qty" style={{ display: "block", fontWeight: 600, fontSize: 13, marginTop: 20, marginBottom: 6 }}>
          Counted quantity{unit ? ` (${unit})` : ""}
        </label>
        <input
          id="counted-qty"
          key={line.id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          autoFocus
          value={draft}
          onChange={e => {
            setDraft(e.target.value);
            if (saveState !== "saving") setSaveState("idle");
          }}
          style={bigInputStyle}
        />

        {message && <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13, marginTop: 8 }}>{message}</div>}
        <div aria-live="polite" style={{ fontSize: 13, marginTop: 8, minHeight: 18 }}>
          {saveState === "saving" && <span style={muted}>Saving...</span>}
          {saveState === "saved" && !dirty && <span style={{ color: "var(--color-success)" }}>Saved. Last saved: {lastSaved}</span>}
          {dirty && saveState !== "saving" && <span style={muted}>Not saved yet</span>}
        </div>

        <button type="submit" disabled={save.isPending || !isOpen} style={{ ...bigButton, marginTop: 8 }}>
          {idx < lines.length - 1 ? "Save and next" : "Save"}
        </button>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button type="button" className="secondary" style={halfButton} disabled={idx === 0} onClick={() => moveTo(idx - 1)}>
            Previous
          </button>
          <button
            type="button"
            className="secondary"
            style={halfButton}
            disabled={idx >= lines.length - 1}
            onClick={() => moveTo(idx + 1)}
          >
            Skip
          </button>
        </div>
      </form>

      <div style={{ marginTop: 20 }}>
        <button
          type="button"
          style={bigButton}
          disabled={!allCounted || submit.isPending}
          onClick={() => {
            setSubmitError(null);
            setConfirming(true);
          }}
        >
          Review and submit
        </button>
        {!allCounted && (
          <div style={{ ...muted, marginTop: 8, textAlign: "center" }}>
            {lines.length - counted} {lines.length - counted === 1 ? "item" : "items"} left to count before you can submit.
          </div>
        )}
      </div>
    </>
  );
}
