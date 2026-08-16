"""
Daily OPS Visit Report — one record per store visit by an Area Manager.
Sections mirror the PDF exactly: FOH, BOH, Admin, General Property,
Events/Dineplan/Reservations, and General Discussion Points.

Section data is stored as JSON dicts for flexibility, each key matching
a line item in the original form. Each value has:
  {"notes": str, "due_date": str | null, "person": str | null}
"""

from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class OpsVisitReport(Base):
    __tablename__ = "ops_visit_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)

    # Header
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    visit_time: Mapped[str] = mapped_column(String(20), nullable=True)
    visit_done_by: Mapped[str] = mapped_column(String(100), nullable=False)
    manager_on_duty: Mapped[str] = mapped_column(String(100), nullable=True)
    gm_of_store: Mapped[str] = mapped_column(String(100), nullable=True)
    store_trading_hours: Mapped[str] = mapped_column(String(50), nullable=True)

    # FOH — keys: lights, tables, decor, brand_standard, floors, hvac, menus, maintenance
    foh: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # BOH — keys: food_quality, expired_products, labelling, cleanliness, ck_supplier, cos_discussion, maintenance
    boh: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Admin — keys: general_concerns
    admin: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # General Property — keys: general_maintenance
    general_property: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Events, Dineplan & Reservations — keys: events
    events: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # General Discussion Points (free text)
    complaints_resolution: Mapped[str] = mapped_column(Text, nullable=True)
    hr_support: Mapped[str] = mapped_column(Text, nullable=True)

    # Signatures (names for now — can be replaced with digital signature URLs)
    mod_signature: Mapped[str] = mapped_column(String(100), nullable=True)
    am_signature: Mapped[str] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["Location"] = relationship()
