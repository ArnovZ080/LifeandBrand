import { useState, useRef } from "react";
import api from "../hooks/useApi";
import type { InvoiceExtraction } from "../types";

export default function InvoiceOCR() {
  const [preview, setPreview] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<InvoiceExtraction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setExtraction(null);
    setPreview(URL.createObjectURL(file));
    setLoading(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await api.post("/invoice-ocr/extract", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setExtraction(res.data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Extraction failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const confidenceColor = {
    high: "var(--color-success)",
    medium: "var(--color-warning)",
    low: "var(--color-danger)",
  };

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>Invoice Capture (OCR)</h1>
      <p style={{ color: "var(--color-text-muted)", marginBottom: 24 }}>
        Photograph or scan a supplier invoice. Claude reads it and pre-fills the form — you review and confirm.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: preview ? "1fr 1fr" : "1fr", gap: 24 }}>
        {/* Upload zone */}
        <div>
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
            style={{
              border: "2px dashed var(--color-border)",
              borderRadius: 8,
              padding: 40,
              textAlign: "center",
              cursor: "pointer",
              background: "#fafafa",
              minHeight: 220,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 32 }}>📄</div>
            <div style={{ fontWeight: 500 }}>Drop invoice image here</div>
            <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>or click to browse — JPEG, PNG, WEBP</div>
            {loading && <div style={{ color: "var(--color-primary)", marginTop: 8 }}>Reading invoice...</div>}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
          />

          {preview && (
            <img
              src={preview}
              alt="Invoice preview"
              style={{ marginTop: 16, maxWidth: "100%", borderRadius: 6, border: "1px solid var(--color-border)" }}
            />
          )}
        </div>

        {/* Extracted data */}
        {extraction && (
          <div>
            <div className="card" style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <h3 style={{ fontWeight: 600 }}>Extracted Data</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Confidence:</span>
                  <span style={{
                    fontWeight: 700, fontSize: 13,
                    color: confidenceColor[extraction.confidence],
                  }}>
                    {extraction.confidence.toUpperCase()}
                  </span>
                </div>
              </div>

              {extraction.extraction_notes && (
                <div style={{
                  background: "#fef3c7", borderRadius: 4, padding: "8px 12px",
                  fontSize: 13, color: "#92400e", marginBottom: 16,
                }}>
                  {extraction.extraction_notes}
                </div>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 20px", marginBottom: 16 }}>
                <Field label="Supplier" value={extraction.supplier_name} />
                <Field label="Invoice #" value={extraction.invoice_number} />
                <Field label="Invoice Date" value={extraction.invoice_date} />
                <Field label="Due Date" value={extraction.due_date} />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px 20px" }}>
                <Field label="Subtotal" value={extraction.subtotal != null ? `R${extraction.subtotal.toFixed(2)}` : null} />
                <Field label="Tax" value={extraction.tax_amount != null ? `R${extraction.tax_amount.toFixed(2)}` : null} />
                <Field
                  label="Total"
                  value={extraction.total_amount != null ? `R${extraction.total_amount.toFixed(2)}` : null}
                  bold
                />
              </div>
            </div>

            <div className="card">
              <h4 style={{ fontWeight: 600, marginBottom: 12 }}>Line Items ({extraction.lines.length})</h4>
              <table>
                <thead>
                  <tr>
                    <th>Description</th>
                    <th>Qty</th>
                    <th>Unit</th>
                    <th>Unit Price</th>
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {extraction.lines.map((ln, i) => (
                    <tr key={i}>
                      <td>{ln.description}</td>
                      <td>{ln.quantity}</td>
                      <td>{ln.unit ?? "—"}</td>
                      <td>R{ln.unit_price.toFixed(2)}</td>
                      <td>R{ln.line_total.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ marginTop: 20, display: "flex", gap: 10 }}>
                <button>Confirm & Save Invoice</button>
                <button className="secondary">Edit Before Saving</button>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div style={{ background: "#fee2e2", padding: 16, borderRadius: 6, color: "#991b1b" }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, bold }: { label: string; value: string | null | undefined; bold?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div style={{ fontWeight: bold ? 700 : 400, marginTop: 2 }}>
        {value ?? <span style={{ color: "var(--color-text-muted)" }}>—</span>}
      </div>
    </div>
  );
}
