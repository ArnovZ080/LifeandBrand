from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from app.services.invoice_ocr import extract_invoice, InvoiceExtraction, ExtractedLine

router = APIRouter(prefix="/invoice-ocr", tags=["invoice-ocr"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class ExtractedLineOut(BaseModel):
    description: str
    quantity: float
    unit: str | None
    unit_price: float
    line_total: float


class InvoiceExtractionOut(BaseModel):
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    subtotal: float | None
    tax_amount: float | None
    total_amount: float | None
    currency: str
    lines: list[ExtractedLineOut]
    confidence: str
    extraction_notes: str | None


@router.post("/extract", response_model=InvoiceExtractionOut)
async def extract(file: UploadFile = File(...)):
    """
    Upload an invoice image (JPEG, PNG, WEBP) and receive structured extraction.
    The result pre-populates the invoice capture form — a human must review and confirm.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported file type '{file.content_type}'. Use JPEG, PNG, or WEBP.")

    image_bytes = await file.read()
    if len(image_bytes) > MAX_SIZE_BYTES:
        raise HTTPException(413, "Image exceeds 10 MB limit. Please compress before uploading.")

    try:
        result = extract_invoice(image_bytes, media_type=file.content_type)
    except Exception as e:
        raise HTTPException(502, f"OCR extraction failed: {str(e)}")

    return InvoiceExtractionOut(
        supplier_name=result.supplier_name,
        invoice_number=result.invoice_number,
        invoice_date=result.invoice_date,
        due_date=result.due_date,
        subtotal=result.subtotal,
        tax_amount=result.tax_amount,
        total_amount=result.total_amount,
        currency=result.currency,
        lines=[
            ExtractedLineOut(
                description=ln.description,
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price=ln.unit_price,
                line_total=ln.line_total,
            )
            for ln in result.lines
        ],
        confidence=result.confidence,
        extraction_notes=result.extraction_notes,
    )
