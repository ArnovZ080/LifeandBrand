from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    ACCEPTED = "accepted"


class Delivery(Base):
    """Goods Received Note (GRN). One PO may have multiple deliveries."""
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    grn_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_delivery_note: Mapped[str] = mapped_column(String(100), nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.PENDING)
    received_by: Mapped[str] = mapped_column(String(100), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="deliveries")
    supplier: Mapped["Supplier"] = relationship()
    location: Mapped["Location"] = relationship()
    lines: Mapped[list["DeliveryLine"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")
    invoice: Mapped["Invoice"] = relationship(back_populates="delivery", uselist=False)


class DeliveryLine(Base):
    __tablename__ = "delivery_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_lines.id"), nullable=True)
    quantity_delivered: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    quantity_accepted: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    has_discrepancy: Mapped[bool] = mapped_column(Boolean, default=False)
    discrepancy_notes: Mapped[str] = mapped_column(Text, nullable=True)

    # Perishable tracking — captured at the point of receiving
    best_before_date: Mapped[date] = mapped_column(Date, nullable=True)
    batch_reference: Mapped[str] = mapped_column(String(100), nullable=True)

    delivery: Mapped["Delivery"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
    po_line: Mapped["PurchaseOrderLine"] = relationship()
    # One batch created per accepted perishable delivery line
    batch: Mapped["ItemBatch"] = relationship(back_populates="delivery_line", uselist=False)
