"""
Full stock counts (Feature 1).

A StockCount is a complete physical count of a site, separate from the
per-department SpotCheckSession. Each line snapshots the system (on-hand)
quantity when the count is created. Submitting the count compares counted
against system, values the variance at the snapshotted unit cost, and posts
ADJUSTMENT StockMovements so on-hand matches the counted quantity.

CountTemplate stores the ordered list of items for a shelf/fridge walk.
"""
from datetime import datetime, date
import enum
from sqlalchemy import (
    String, DateTime, Date, Numeric, ForeignKey, Text, Enum, JSON, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class StockCountStatus(str, enum.Enum):
    OPEN = "open"
    SUBMITTED = "submitted"


def _enum_values(enum_cls):
    # Store lowercase values so the column matches the labels in migration 0005.
    return [member.value for member in enum_cls]


class CountTemplate(Base):
    __tablename__ = "count_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=True)  # null = all sites
    item_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # ordered count route
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockCount(Base):
    __tablename__ = "stock_counts"
    __table_args__ = (Index("ix_stock_counts_unit_date", "org_unit_id", "count_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("count_templates.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    count_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[StockCountStatus] = mapped_column(
        Enum(StockCountStatus, name="stockcountstatus", values_callable=_enum_values),
        nullable=False,
        default=StockCountStatus.OPEN,
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    org_unit: Mapped["OrgUnit"] = relationship()
    template: Mapped["CountTemplate"] = relationship()
    lines: Mapped[list["StockCountLine"]] = relationship(
        back_populates="stock_count", cascade="all, delete-orphan",
        order_by="StockCountLine.id",
    )


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (
        UniqueConstraint("stock_count_id", "item_id", name="uq_stock_count_lines_count_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)

    system_qty: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)  # on-hand snapshot at creation
    counted_qty: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)  # null = not yet counted
    variance_qty: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)  # counted - system
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    variance_value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    counted_by: Mapped[str] = mapped_column(String(100), nullable=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    stock_count: Mapped["StockCount"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
