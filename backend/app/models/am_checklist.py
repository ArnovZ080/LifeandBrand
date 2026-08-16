"""
Area Manager Operating Structure — checklist task definitions and completion tracking.

Tasks are seeded from constants (matching the PDF exactly) and referenced by ID.
Completions are recorded per location per period (day / week / month).
"""

from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Boolean, Text, ForeignKey, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class ChecklistFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ADHOC = "adhoc"


class AMChecklistTask(Base):
    """Static task definitions. Seeded once — edit via migration if tasks change."""
    __tablename__ = "am_checklist_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    frequency: Mapped[ChecklistFrequency] = mapped_column(Enum(ChecklistFrequency), nullable=False)
    order_num: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    entries: Mapped[list["AMChecklistEntry"]] = relationship(back_populates="task")


class AMChecklistEntry(Base):
    """
    One completion record per task per location per period.
    period_date = the day (daily), Monday of the week (weekly), or first of month (monthly).
    """
    __tablename__ = "am_checklist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("am_checklist_tasks.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)

    # AM completion
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_by: Mapped[str] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    # RM validation
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_by: Mapped[str] = mapped_column(String(100), nullable=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["AMChecklistTask"] = relationship(back_populates="entries")
    location: Mapped["Location"] = relationship()
