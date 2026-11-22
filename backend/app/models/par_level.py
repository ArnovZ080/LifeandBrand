"""Per-venue par levels (shopping list feature).

A par level is the target stock a site wants to hold for one item. The reorder
point is the on-hand figure at or below which the item goes on the shopping
list. Items.reorder_level is a single global figure and is not used here.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ParLevel(Base):
    __tablename__ = "par_levels"
    __table_args__ = (
        UniqueConstraint("org_unit_id", "item_id", name="uq_par_levels_unit_item"),
        Index("ix_par_levels_org_unit", "org_unit_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    par_qty: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    reorder_point: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
