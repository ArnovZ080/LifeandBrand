from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str] = mapped_column(String(50), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    sage_supplier_id: Mapped[str] = mapped_column(String(100), nullable=True)  # Sage reference
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    supplier_items: Mapped[list["SupplierItem"]] = relationship(back_populates="supplier")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="supplier")


class SupplierItem(Base):
    """Price catalogue: which items a supplier sells, at what price."""
    __tablename__ = "supplier_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    supplier_sku: Mapped[str] = mapped_column(String(100), nullable=True)  # supplier's own code
    supplier_item_name: Mapped[str] = mapped_column(String(200), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    pack_size: Mapped[float] = mapped_column(Numeric(10, 4), default=1)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)  # preferred supplier for this item
    effective_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    supplier: Mapped["Supplier"] = relationship(back_populates="supplier_items")
    item: Mapped["Item"] = relationship(back_populates="supplier_items")
