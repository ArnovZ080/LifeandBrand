from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    MATCHED = "matched"       # matched to a GRN
    APPROVED = "approved"     # approved for payment
    POSTED = "posted"         # posted to Sage
    DISPUTED = "disputed"


class Invoice(Base):
    """Supplier invoice. Must be matched to a Delivery (GRN) before approval."""
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=True)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    sage_invoice_id: Mapped[str] = mapped_column(String(100), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    supplier: Mapped["Supplier"] = relationship(back_populates="invoices")
    delivery: Mapped["Delivery"] = relationship(back_populates="invoice")
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
