"""
Vendor Price Catalogue (Phase 0 Foundation).

Date-effective supplier prices per item, optionally scoped to a single
org unit (org_unit_id null = tenant-wide price). Complements the legacy
SupplierItem table, which stays untouched during transition.
"""
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class VendorPriceCatalogue(Base):
    __tablename__ = "vendor_price_catalogue"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=True)  # null = tenant-wide
    price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    item: Mapped["Item"] = relationship()
    supplier: Mapped["Supplier"] = relationship()
    org_unit: Mapped["OrgUnit"] = relationship()
