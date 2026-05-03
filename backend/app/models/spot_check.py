from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
from app.models.item import Department
import enum


class SpotCheckStatus(str, enum.Enum):
    PENDING = "pending"       # sent to manager, awaiting counts
    PARTIAL = "partial"       # some counts submitted
    COMPLETE = "complete"     # all counts submitted and variance calculated
    MISSED = "missed"         # window closed without completion


class SpotCheckSession(Base):
    """
    A daily spot-check session for one department.
    Two sessions per day are typical (morning and afternoon).
    """
    __tablename__ = "spot_check_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    department: Mapped[Department] = mapped_column(Enum(Department), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1 = morning, 2 = afternoon
    status: Mapped[SpotCheckStatus] = mapped_column(Enum(SpotCheckStatus), default=SpotCheckStatus.PENDING)
    assigned_to: Mapped[str] = mapped_column(String(200), nullable=True)  # manager name / contact
    notified_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["Location"] = relationship()
    items: Mapped[list["SpotCheckItem"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SpotCheckItem(Base):
    """One item selected for counting in a spot-check session."""
    __tablename__ = "spot_check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("spot_check_sessions.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)

    # Selection metadata — why was this item chosen?
    selection_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    sales_velocity_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    variance_history_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)
    days_since_last_check: Mapped[int] = mapped_column(Integer, nullable=True)

    # Expected (theoretical) closing stock at time of check
    theoretical_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)

    # Actual count submitted by manager
    actual_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    counted_by: Mapped[str] = mapped_column(String(100), nullable=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    # Calculated on count submission
    variance_quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    variance_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    variance_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=True)

    session: Mapped["SpotCheckSession"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="spot_check_items")
