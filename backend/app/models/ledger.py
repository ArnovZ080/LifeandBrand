"""
Accuracy Ledger (Phase 0 Foundation).

Every metric the platform computes (net_sales, cos_pct, ...) is checked
against ground truth per org unit per period. A metric earns "green" status
for an org unit once it has `required_green_periods` consecutive
within-tolerance entries — that status is derived by a service, not stored.
"""
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Boolean, ForeignKey, Float, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Metric(Base):
    __tablename__ = "ledger_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # e.g. "net_sales"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    # ±tolerance as a percentage, e.g. 0.5 means ±0.5%
    tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False)
    required_green_periods: Mapped[int] = mapped_column(Integer, default=14)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="metric")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("ledger_metrics.id"), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    computed_value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    ground_truth_value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    # Null until ground truth arrives and the comparison is made
    within_tolerance: Mapped[bool] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    metric: Mapped["Metric"] = relationship(back_populates="entries")
    org_unit: Mapped["OrgUnit"] = relationship()
