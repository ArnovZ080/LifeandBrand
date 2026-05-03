"""
Invoice OCR using Claude's vision API.

Workflow:
  1. Receive image bytes (JPEG/PNG) or PDF first-page render
  2. Send to Claude claude-sonnet-4-6 with a structured extraction prompt
  3. Return a parsed InvoiceExtraction that pre-populates the invoice form
  4. A human reviews and confirms before the invoice is saved

Why Claude over a dedicated OCR service:
  - Handles messy, non-standard invoice layouts without templates
  - Understands context (e.g. distinguishes "qty" from "pack size" columns)
  - Returns structured JSON directly — no post-processing regex needed
  - Works on handwritten delivery notes too
"""

import base64
import json
from dataclasses import dataclass, field
from anthropic import Anthropic

client = Anthropic()

EXTRACTION_PROMPT = """You are extracting structured data from a supplier invoice or delivery note.

Return ONLY valid JSON matching this exact structure — no explanation, no markdown:

{
  "supplier_name": "string or null",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "subtotal": number or null,
  "tax_amount": number or null,
  "total_amount": number or null,
  "currency": "ZAR",
  "lines": [
    {
      "description": "string",
      "quantity": number,
      "unit": "string or null",
      "unit_price": number,
      "line_total": number
    }
  ],
  "confidence": "high|medium|low",
  "extraction_notes": "any caveats about hard-to-read sections, or null"
}

Rules:
- Dates must be ISO 8601 (YYYY-MM-DD). Infer year from context if not explicit.
- All monetary values as numbers, no currency symbols.
- If a field is absent or illegible, use null — do not guess.
- confidence = "high" if >90% of fields are clearly legible,
               "medium" if some fields required inference,
               "low" if image quality is poor or layout is non-standard.
"""


@dataclass
class ExtractedLine:
    description: str
    quantity: float
    unit: str | None
    unit_price: float
    line_total: float


@dataclass
class InvoiceExtraction:
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    subtotal: float | None
    tax_amount: float | None
    total_amount: float | None
    currency: str
    lines: list[ExtractedLine]
    confidence: str
    extraction_notes: str | None
    raw_response: str  # kept for audit/debugging


def extract_invoice(image_bytes: bytes, media_type: str = "image/jpeg") -> InvoiceExtraction:
    """
    Send an invoice image to Claude and return structured extraction.

    Args:
        image_bytes: Raw bytes of the image (JPEG, PNG, or WEBP).
        media_type:  MIME type of the image.

    Returns:
        InvoiceExtraction with parsed fields and a confidence rating.
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=EXTRACTION_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all invoice data from this image.",
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Claude occasionally wraps JSON in a code block — strip it
        stripped = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(stripped)

    lines = [
        ExtractedLine(
            description=ln["description"],
            quantity=float(ln["quantity"]),
            unit=ln.get("unit"),
            unit_price=float(ln["unit_price"]),
            line_total=float(ln["line_total"]),
        )
        for ln in data.get("lines", [])
    ]

    return InvoiceExtraction(
        supplier_name=data.get("supplier_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        due_date=data.get("due_date"),
        subtotal=data.get("subtotal"),
        tax_amount=data.get("tax_amount"),
        total_amount=data.get("total_amount"),
        currency=data.get("currency", "ZAR"),
        lines=lines,
        confidence=data.get("confidence", "low"),
        extraction_notes=data.get("extraction_notes"),
        raw_response=raw,
    )
