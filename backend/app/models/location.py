"""
OrgUnit — replaces the former flat Location model.

The table is renamed locations → org_units in migration 0001.
All dependent tables keep their `location_id` FK column name (pointing at
org_units.id) to minimise diff across the codebase.

Tier hierarchy: SITE (leaf) → AREA → REGIONAL → NATIONAL → MD → CEO
"""
from datetime import datetime
import enum
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class OrgTier(str, enum.Enum):
    SITE = "site"
    AREA = "area"
    REGIONAL = "regional"
    NATIONAL = "national"
    MD = "md"
    CEO = "ceo"


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=True)
    tier: Mapped[OrgTier] = mapped_column(Enum(OrgTier), nullable=False, default=OrgTier.SITE)
    parent_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=True)
    pos_site_code: Mapped[str] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped["OrgUnit"] = relationship(remote_side="OrgUnit.id", back_populates="children")
    children: Mapped[list["OrgUnit"]] = relationship(back_populates="parent")
    brand: Mapped["Brand"] = relationship(back_populates="org_units")

    # Relationships carried over from Location
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="location")
    sales: Mapped[list["Sale"]] = relationship(back_populates="location")


# Alias so any code that still imports `Location` doesn't immediately break
Location = OrgUnit
# Register the alias in the declarative class registry so relationship
# annotations like Mapped["Location"] (delivery, am_checklist, ops_visit,
# one_on_one) resolve to OrgUnit during mapper configuration.
Base.registry._class_registry["Location"] = OrgUnit
