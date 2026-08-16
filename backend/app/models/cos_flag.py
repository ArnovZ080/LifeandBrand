"""
COS variance flags (Phase 2).

A CosFlag is raised for an item at an org unit in a period ("YYYY-MM") when
|actual usage value - theoretical usage value| exceeds the configured
threshold. The classifier suggests a cause; managers can dismiss flags with a
reason (recorded as CosDismissal, keeping the flag row for history).
"""
from datetime import datetime
import enum
from sqlalchemy import String, DateTime, ForeignKey, Enum, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class CosCause(str, enum.Enum):
    COUNTING_SWAP = "counting_swap"      # offsetting variances between similar items
    TIMING = "timing"                    # variance reverses across consecutive periods
    SPILLAGE = "spillage"                # small persistent negative on high-prep items
    PROCESS_FAILURE = "process_failure"  # recurring same-direction variance >= 3 periods
    IMMEDIATE = "immediate"              # single large spike
    KNOWN_BASELINE = "known_baseline"    # previously dismissed for the same item


class CosFlag(Base):
    __tablename__ = "cos_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    actual_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=True)
    theoretical_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=True)
    variance_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=True)
    variance_value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    cause: Mapped[CosCause] = mapped_column(Enum(CosCause), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org_unit: Mapped["OrgUnit"] = relationship()
    item: Mapped["Item"] = relationship()
    dismissals: Mapped[list["CosDismissal"]] = relationship(back_populates="flag")


class CosDismissal(Base):
    __tablename__ = "cos_dismissals"

    id: Mapped[int] = mapped_column(primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("cos_flags.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    dismissed_by: Mapped[str] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    flag: Mapped["CosFlag"] = relationship(back_populates="dismissals")
