import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import api from "../hooks/useApi";

const LOCATION_ID = 1;

interface VisitSummary {
  id: number;
  location_id: number;
  visit_date: string;
  visit_done_by: string;
  gm_of_store: string | null;
  created_at: string;
}

interface SectionItem {
  notes: string;
  due_date: string;
  person: string;
}

interface VisitPayload {
  location_id: number;
  visit_date: string;
  visit_time: string;
  visit_done_by: string;
  manager_on_duty: string;
  gm_of_store: string;
  store_trading_hours: string;
  foh: Record<string, SectionItem>;
  boh: Record<string, SectionItem>;
  admin: Record<string, SectionItem>;
  general_property: Record<string, SectionItem>;
  events: Record<string, SectionItem>;
  complaints_resolution: string;
  hr_support: string;
  mod_signature: string;
  am_signature: string;
}

const FOH_ITEMS = [
  "Lights",
  "Tables & Chairs",
  "Décor",
  "Brand Standard",
  "Floors & Surfaces",
  "HVAC / Air Quality",
  "Menus & POS",
  "Maintenance Issues",
];

const BOH_ITEMS = [
  "Food Quality & Presentation",
  "Expired Products",
  "Labelling & Dating",
  "Cleanliness & Hygiene",
  "CK Supplier Compliance",
  "COS Discussion",
  "Maintenance Issues",
];

const ADMIN_ITEMS = [
  "Rosters & Scheduling",
  "Petty Cash",
  "Incident Reports",
  "Staff Files Up-to-Date",
  "Training Records",
];

const PROPERTY_ITEMS = [
  "Exterior Cleanliness",
  "Parking & Entrance",
  "Signage",
  "Security",
  "Utilities / Readings",
];

const EVENTS_ITEMS = [
  "Upcoming Reservations",
  "Dineplan Accuracy",
  "Function Bookings",
  "Deposit Records",
];

type Section = "foh" | "boh" | "admin" | "general_property" | "events";

function emptySectionItems(keys: string[]): Record<string, SectionItem> {
  return Object.fromEntries(keys.map(k => [k, { notes: "", due_date: "", person: "" }]));
}

function emptyPayload(): VisitPayload {
  const today = new Date().toISOString().slice(0, 10);
  const now = new Date().toTimeString().slice(0, 5);
  return {
    location_id: LOCATION_ID,
    visit_date: today,
    visit_time: now,
    visit_done_by: "",
    manager_on_duty: "",
    gm_of_store: "",
    store_trading_hours: "",
    foh: emptySectionItems(FOH_ITEMS),
    boh: emptySectionItems(BOH_ITEMS),
    admin: emptySectionItems(ADMIN_ITEMS),
    general_property: emptySectionItems(PROPERTY_ITEMS),
    events: emptySectionItems(EVENTS_ITEMS),
    complaints_resolution: "",
    hr_support: "",
    mod_signature: "",
    am_signature: "",
  };
}

export default function OpsVisitReport() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<VisitPayload>(emptyPayload);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const { data: visits = [], isLoading } = useQuery<VisitSummary[]>({
    queryKey: ["ops-visits", LOCATION_ID],
    queryFn: () => api.get(`/am/ops-visits/?location_id=${LOCATION_ID}`).then(r => r.data),
  });

  const { data: detail } = useQuery({
    queryKey: ["ops-visit-detail", viewingId],
    queryFn: () => api.get(`/am/ops-visits/${viewingId}`).then(r => r.data),
    enabled: viewingId !== null,
  });

  const createMutation = useMutation({
    mutationFn: (payload: VisitPayload) => api.post("/am/ops-visits/", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ops-visits"] });
      setShowForm(false);
      setForm(emptyPayload());
    },
  });

  function setHeader(field: keyof VisitPayload, value: string) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function setSectionItem(section: Section, key: string, field: keyof SectionItem, value: string) {
    setForm(f => ({
      ...f,
      [section]: { ...f[section], [key]: { ...f[section][key], [field]: value } },
    }));
  }

  if (viewingId !== null && detail) {
    return <DetailView report={detail} onBack={() => setViewingId(null)} />;
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Daily OPS Visit Reports</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            Per-store operational visit assessments completed by the Area Manager.
          </p>
        </div>
        <button onClick={() => setShowForm(true)}>+ New Visit Report</button>
      </div>

      {isLoading ? (
        <div>Loading...</div>
      ) : visits.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>
          No visit reports yet. Click "New Visit Report" to create the first one.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--color-surface-alt, #f9fafb)" }}>
                {["Visit Date", "Done By", "GM on Duty", "Created", ""].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 12, fontWeight: 600, borderBottom: "1px solid var(--color-border)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visits.map((v, idx) => (
                <tr key={v.id} style={{ borderBottom: idx < visits.length - 1 ? "1px solid var(--color-border)" : "none" }}>
                  <td style={{ padding: "12px 16px", fontSize: 13, fontWeight: 500 }}>{v.visit_date}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13 }}>{v.visit_done_by}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13 }}>{v.gm_of_store || "—"}</td>
                  <td style={{ padding: "12px 16px", fontSize: 13, color: "var(--color-text-muted)" }}>
                    {new Date(v.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <button className="secondary" style={{ fontSize: 12, padding: "4px 10px" }}
                      onClick={() => setViewingId(v.id)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", overflowY: "auto", zIndex: 100 }}>
          <div className="card" style={{ maxWidth: 720, margin: "32px auto", padding: 32 }}>
            <h2 style={{ fontWeight: 700, fontSize: 18, marginBottom: 20 }}>New OPS Visit Report</h2>

            {/* Header */}
            <SectionHeading>Visit Details</SectionHeading>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
              <Field label="Visit Date">
                <input type="date" value={form.visit_date} onChange={e => setHeader("visit_date", e.target.value)} />
              </Field>
              <Field label="Visit Time">
                <input type="time" value={form.visit_time} onChange={e => setHeader("visit_time", e.target.value)} />
              </Field>
              <Field label="Visit Done By *">
                <input value={form.visit_done_by} onChange={e => setHeader("visit_done_by", e.target.value)} placeholder="Area Manager name" />
              </Field>
              <Field label="Manager on Duty">
                <input value={form.manager_on_duty} onChange={e => setHeader("manager_on_duty", e.target.value)} />
              </Field>
              <Field label="GM of Store">
                <input value={form.gm_of_store} onChange={e => setHeader("gm_of_store", e.target.value)} />
              </Field>
              <Field label="Trading Hours">
                <input value={form.store_trading_hours} onChange={e => setHeader("store_trading_hours", e.target.value)} placeholder="e.g. 07:00–22:00" />
              </Field>
            </div>

            <SectionBlock title="FOH (Front of House)" items={FOH_ITEMS} section="foh" data={form.foh} onChange={setSectionItem} />
            <SectionBlock title="BOH (Back of House)" items={BOH_ITEMS} section="boh" data={form.boh} onChange={setSectionItem} />
            <SectionBlock title="Administration" items={ADMIN_ITEMS} section="admin" data={form.admin} onChange={setSectionItem} />
            <SectionBlock title="General Property" items={PROPERTY_ITEMS} section="general_property" data={form.general_property} onChange={setSectionItem} />
            <SectionBlock title="Events / Dineplan / Reservations" items={EVENTS_ITEMS} section="events" data={form.events} onChange={setSectionItem} />

            {/* General Discussion */}
            <SectionHeading>General Discussion Points</SectionHeading>
            <Field label="Complaints & Resolution">
              <textarea rows={3} value={form.complaints_resolution}
                onChange={e => setHeader("complaints_resolution", e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, resize: "vertical", font: "inherit" }} />
            </Field>
            <Field label="HR Support">
              <textarea rows={3} value={form.hr_support}
                onChange={e => setHeader("hr_support", e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 4, resize: "vertical", font: "inherit" }} />
            </Field>

            {/* Signatures */}
            <SectionHeading>Signatures</SectionHeading>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>
              <Field label="MOD Signature">
                <input value={form.mod_signature} onChange={e => setHeader("mod_signature", e.target.value)} placeholder="Manager on Duty name" />
              </Field>
              <Field label="AM Signature">
                <input value={form.am_signature} onChange={e => setHeader("am_signature", e.target.value)} placeholder="Area Manager name" />
              </Field>
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                disabled={!form.visit_done_by || createMutation.isPending}
                onClick={() => createMutation.mutate(form)}
                style={{ background: "#2563eb" }}
              >
                {createMutation.isPending ? "Saving..." : "Save Visit Report"}
              </button>
              <button className="secondary" onClick={() => { setShowForm(false); setForm(emptyPayload()); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SectionBlock({
  title, items, section, data, onChange,
}: {
  title: string;
  items: string[];
  section: Section;
  data: Record<string, SectionItem>;
  onChange: (section: Section, key: string, field: keyof SectionItem, value: string) => void;
}) {
  return (
    <>
      <SectionHeading>{title}</SectionHeading>
      <div style={{ marginBottom: 20 }}>
        {items.map(item => (
          <div key={item} style={{ marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--color-border)" }}>
            <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6 }}>{item}</div>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 8 }}>
              <input
                placeholder="Notes / observations"
                value={data[item]?.notes || ""}
                onChange={e => onChange(section, item, "notes", e.target.value)}
                style={{ fontSize: 12 }}
              />
              <input
                type="date"
                title="Due date"
                value={data[item]?.due_date || ""}
                onChange={e => onChange(section, item, "due_date", e.target.value)}
                style={{ fontSize: 12 }}
              />
              <input
                placeholder="Responsible person"
                value={data[item]?.person || ""}
                onChange={e => onChange(section, item, "person", e.target.value)}
                style={{ fontSize: 12 }}
              />
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function DetailView({ report, onBack }: { report: any; onBack: () => void }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <button className="secondary" onClick={onBack}>← Back</button>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>
            OPS Visit — {report.visit_date}
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>
            Done by {report.visit_done_by}{report.gm_of_store ? ` · GM: ${report.gm_of_store}` : ""}
          </p>
        </div>
      </div>

      {([
        ["FOH (Front of House)", report.foh],
        ["BOH (Back of House)", report.boh],
        ["Administration", report.admin],
        ["General Property", report.general_property],
        ["Events / Dineplan", report.events],
      ] as [string, Record<string, any>][]).map(([heading, section]) => (
        <div key={heading} className="card" style={{ marginBottom: 16, padding: 0 }}>
          <div style={{ padding: "10px 16px", background: "#f3f4f6", borderRadius: "8px 8px 0 0", fontWeight: 600, fontSize: 13 }}>
            {heading}
          </div>
          {Object.entries(section).map(([item, val]: [string, any]) => (
            (val.notes || val.due_date || val.person) ? (
              <div key={item} style={{ padding: "10px 16px", borderBottom: "1px solid var(--color-border)", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, fontSize: 13 }}>
                <div><strong>{item}</strong>{val.notes ? <div style={{ color: "var(--color-text-muted)", fontSize: 12, marginTop: 2 }}>{val.notes}</div> : null}</div>
                <div style={{ color: "var(--color-text-muted)" }}>{val.due_date ? `Due: ${val.due_date}` : ""}</div>
                <div style={{ color: "var(--color-text-muted)" }}>{val.person || ""}</div>
              </div>
            ) : null
          ))}
        </div>
      ))}

      {(report.complaints_resolution || report.hr_support) && (
        <div className="card" style={{ marginBottom: 16, padding: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>General Discussion Points</div>
          {report.complaints_resolution && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-muted)" }}>Complaints & Resolution</div>
              <div style={{ fontSize: 13 }}>{report.complaints_resolution}</div>
            </div>
          )}
          {report.hr_support && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-muted)" }}>HR Support</div>
              <div style={{ fontSize: 13 }}>{report.hr_support}</div>
            </div>
          )}
        </div>
      )}

      {(report.mod_signature || report.am_signature) && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>Signatures</div>
          <div style={{ display: "flex", gap: 32, fontSize: 13 }}>
            {report.mod_signature && <div><span style={{ color: "var(--color-text-muted)" }}>MOD: </span>{report.mod_signature}</div>}
            {report.am_signature && <div><span style={{ color: "var(--color-text-muted)" }}>AM: </span>{report.am_signature}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontWeight: 600, fontSize: 14, borderBottom: "2px solid #2563eb", paddingBottom: 4, marginBottom: 12, color: "#2563eb" }}>
      {children}
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
