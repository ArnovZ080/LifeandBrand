"""
Budgets (Phase 0 Foundation).

One row per org unit / year / month / metric key (e.g. "net_sales",
"cos_pct"). Actuals vs budget comparisons are computed by services.
"""
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("org_unit_id", "year", "month", "metric_key", name="uq_budget_unit_period_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "net_sales", "cos_pct"
    value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org_unit: Mapped["OrgUnit"] = relationship()
