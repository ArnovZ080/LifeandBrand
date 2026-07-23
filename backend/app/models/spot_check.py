from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
from app.models.item import Department
import enum


class SpotCheckStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETE = "complete"
    MISSED = "missed"


class SpotCheckSession(Base):
    """
    A daily spot-check session for one department.
    Two sessions per day: slot 1 (morning), slot 2 (afternoon/evening).
    Session size varies — the algorithm guarantees a 7-day full-rotation cycle
    by forcing overdue items into the session regardless of the base count.
    """
    __tablename__ = "spot_check_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    department: Mapped[Department] = mapped_column(Enum(Department), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[SpotCheckStatus] = mapped_column(Enum(SpotCheckStatus), default=SpotCheckStatus.PENDING)
    assigned_to: Mapped[str] = mapped_column(String(200), nullable=True)
    notified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["OrgUnit"] = relationship()
    items: Mapped[list["SpotCheckItem"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SpotCheckItem(Base):
    """One item selected for a spot-check. For perishable items, the actual
    counted quantities are broken out per batch via SpotCheckBatchCount."""
    __tablename__ = "spot_check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("spot_check_sessions.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)

    # Why this item was selected
    selection_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    velocity_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    value_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    variance_history_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    days_since_last_check: Mapped[int] = mapped_column(Integer, nullable=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)  # forced in by 7-day rule

    # For non-perishable items: single count
    is_perishable: Mapped[bool] = mapped_column(Boolean, default=False)
    theoretical_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    actual_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    counted_by: Mapped[str] = mapped_column(String(100), nullable=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    variance_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    variance_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    variance_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)

    session: Mapped["SpotCheckSession"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="spot_check_items")
    # Populated for perishable items — one row per active batch
    batch_counts: Mapped[list["SpotCheckBatchCount"]] = relationship(
        back_populates="spot_check_item", cascade="all, delete-orphan"
    )


class SpotCheckBatchCount(Base):
    """
    Per-batch count for a perishable SpotCheckItem.
    The manager counts each batch separately so expiry can be flagged
    at the batch level, not just as a total variance.
    """
    __tablename__ = "spot_check_batch_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    spot_check_item_id: Mapped[int] = mapped_column(ForeignKey("spot_check_items.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("item_batches.id"), nullable=False)

    received_date: Mapped[date] = mapped_column(Date, nullable=True)
    best_before_date: Mapped[date] = mapped_column(Date, nullable=True)
    batch_reference: Mapped[str] = mapped_column(String(100), nullable=True)

    expected_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    actual_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    counted_by: Mapped[str] = mapped_column(String(100), nullable=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    variance_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    days_until_expiry: Mapped[int] = mapped_column(Integer, nullable=True)  # negative = already expired

    spot_check_item: Mapped["SpotCheckItem"] = relationship(back_populates="batch_counts")
    batch: Mapped["ItemBatch"] = relationship(back_populates="spot_check_batch_counts")
