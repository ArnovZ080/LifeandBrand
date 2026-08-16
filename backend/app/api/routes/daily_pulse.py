"""
Daily Pulse (Phase 1) — the site P&L heartbeat.

MTD L2 net sales with comparators (last year, budget, prior month, portfolio
share), a straight-line month-end projection, and the accuracy-ledger status
for the net_sales metric. Every field is null when its base data is missing.
"""
import calendar
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models import Budget, OrgUnit
from app.models.location import OrgTier
from app.models.user import User
from app.services import ledger_service
from app.services.net_sales import net_sales

router = APIRouter(prefix="/daily-pulse", tags=["daily-pulse"])


class Comparators(BaseModel):
    vs_last_year_pct: float | None
    vs_budget_pct: float | None
    vs_prior_month_pct: float | None
    portfolio_share_pct: float | None


class DailyPulseOut(BaseModel):
    org_unit_id: int
    business_date: date
    mtd_net_sales: float | None
    comparators: Comparators
    projection_month_end: float | None
    covers_mtd: int | None
    spend_per_head: float | None
    ledger_status: str


def _pct_change(current: Decimal | None, base: Decimal | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round(float((current - base) / base * 100), 2)


def _clamped_window(year: int, month: int, day_count: int) -> tuple[date, date]:
    """First `day_count` days of (year, month), clamped to the month length."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, min(day_count, last))


@router.get("/", response_model=DailyPulseOut)
def daily_pulse(
    org_unit_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        raise HTTPException(404, "Org unit not found")

    today = date.today()
    month_start = today.replace(day=1)
    elapsed_days = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    mtd = net_sales(db, org_unit_id, month_start, today, level="L2")

    # ── comparators ─────────────────────────────────────────────────────────────
    ly_from, ly_to = _clamped_window(today.year - 1, today.month, elapsed_days)
    last_year = net_sales(db, org_unit_id, ly_from, ly_to, level="L2")

    pm_year = today.year if today.month > 1 else today.year - 1
    pm_month = today.month - 1 if today.month > 1 else 12
    pm_from, pm_to = _clamped_window(pm_year, pm_month, elapsed_days)
    prior_month = net_sales(db, org_unit_id, pm_from, pm_to, level="L2")

    budget_row = db.execute(
        select(Budget).where(
            Budget.org_unit_id == org_unit_id,
            Budget.year == today.year,
            Budget.month == today.month,
            Budget.metric_key == "net_sales",
        )
    ).scalars().first()
    vs_budget_pct = None
    if budget_row is not None and mtd is not None:
        prorated = Decimal(str(budget_row.value)) * elapsed_days / days_in_month
        vs_budget_pct = _pct_change(mtd, prorated)

    portfolio_share_pct = None
    if mtd is not None:
        site_ids = db.execute(
            select(OrgUnit.id).where(OrgUnit.tier == OrgTier.SITE, OrgUnit.is_active.is_(True))
        ).scalars().all()
        portfolio_total = Decimal(0)
        for sid in site_ids:
            site_mtd = net_sales(db, sid, month_start, today, level="L2")
            if site_mtd is not None:
                portfolio_total += site_mtd
        if portfolio_total > 0:
            portfolio_share_pct = round(float(mtd / portfolio_total * 100), 2)

    projection = (
        round(float(mtd / elapsed_days * days_in_month), 2) if mtd is not None else None
    )

    # covers: the Sale model has no covers column yet → null (spend/head too)
    covers_mtd = None
    spend_per_head = None

    # ── accuracy ledger ───────────────────────────────────────────────────────
    ledger_service.ensure_metric(db, "net_sales", "Net sales (L2)", 0.5, 14)
    if mtd is not None:
        ledger_service.record_entry(db, "net_sales", org_unit_id, today, float(mtd))
    status = ledger_service.ledger_status(db, "net_sales", org_unit_id)

    return DailyPulseOut(
        org_unit_id=org_unit_id,
        business_date=today,
        mtd_net_sales=round(float(mtd), 2) if mtd is not None else None,
        comparators=Comparators(
            vs_last_year_pct=_pct_change(mtd, last_year),
            vs_budget_pct=vs_budget_pct,
            vs_prior_month_pct=_pct_change(mtd, prior_month),
            portfolio_share_pct=portfolio_share_pct,
        ),
        projection_month_end=projection,
        covers_mtd=covers_mtd,
        spend_per_head=spend_per_head,
        ledger_status=status,
    )
