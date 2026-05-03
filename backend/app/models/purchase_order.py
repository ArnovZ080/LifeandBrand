from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Boolean, Numeric, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class POStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus), default=POStatus.DRAFT)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    location: Mapped["Location"] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="purchase_order")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    supplier_item_id: Mapped[int] = mapped_column(ForeignKey("supplier_items.id"), nullable=True)
    quantity_ordered: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    quantity_received: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
    supplier_item: Mapped["SupplierItem"] = relationship()
