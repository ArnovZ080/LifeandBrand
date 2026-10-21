"""
Sales forecast runs and their lines (Feature 4).

A ForecastRun covers one site from run_date for horizon_days business dates.
Each ForecastLine is one menu item on one business date. baseline_qty is the
computed forecast; adjusted_qty is an optional manager override. The effective
quantity used for ordering is the adjustment when set, otherwise the baseline.
"""
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    String, DateTime, Date, Integer, Numeric, ForeignKey, Text, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (Index("ix_forecast_runs_unit_date", "org_unit_id", "run_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)  # first business date the run covers
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    history_days: Mapped[int] = mapped_column(Integer, nullable=False)  # sales days used for the baseline
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    org_unit: Mapped["OrgUnit"] = relationship()
    lines: Mapped[list["ForecastLine"]] = relationship(
        back_populates="forecast_run", cascade="all, delete-orphan",
        order_by="ForecastLine.id",
    )


class ForecastLine(Base):
    __tablename__ = "forecast_lines"
    __table_args__ = (
        UniqueConstraint("forecast_run_id", "business_date", "menu_item_id",
                         name="uq_forecast_lines_run_date_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    baseline_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    adjusted_qty: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    adjusted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adjustment_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    forecast_run: Mapped["ForecastRun"] = relationship(back_populates="lines")
    menu_item: Mapped["MenuItem"] = relationship()

    @property
    def effective_qty(self) -> Decimal:
        value = self.adjusted_qty if self.adjusted_qty is not None else self.baseline_qty
        return Decimal(str(value)) if value is not None else Decimal(0)
