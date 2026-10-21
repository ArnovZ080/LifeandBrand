"""
Sales forecasting (Feature 4). Method name: seasonal_baseline_v1.

This is a transparent average, not a fitted model. It has no trend, promotion
or holiday terms, and no parameters are estimated from the data.

How a run is computed:
  * Actuals come from the existing sales tables. An item's daily quantity is
    the sum of SaleLine.quantity_sold for the Sale of the site on that business
    date, grouped by MenuItem. Only dates with at least one item line count as
    sales days.
  * A run starting on start_date uses the 8 weeks (56 days) of history that end
    the day before start_date. Nothing on or after start_date is used.
  * For a target date with weekday W, the baseline for a menu item is the mean
    of that item's sold quantity over the sales days in the window that fall on
    weekday W. The divisor is the number of those sales days, so a weekday
    with no item sales on it does not count as zero demand.
  * An item with no sales on weekday W in the window forecasts 0.
  * A run is refused (ForecastError) when the window holds fewer than 28 sales days.
  * A manager may set adjusted_qty on a line. The effective quantity is the
    adjustment when set, otherwise the baseline. Every adjustment is audited.
  * accuracy() compares past effective quantities with posted sales. MAPE is
    taken over item-days with actual sales above zero. WAPE (sum of absolute
    error over sum of actuals) is the overall weighted error.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.forecast import ForecastLine, ForecastRun
from app.models.location import OrgTier, OrgUnit
from app.models.recipe import RecipeLine
from app.models.sale import Sale, SaleLine
from app.models.user import User
from app.services import audit_service

METHOD = "seasonal_baseline_v1"
HISTORY_WEEKS = 8
MIN_SALES_DAYS = 28
MAX_HORIZON_DAYS = 90
QTY = Decimal("0.001")
ZERO = Decimal(0)


class ForecastError(Exception):
    """A forecast cannot be produced from the available history."""


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def require_site(db: Session, org_unit_id: int) -> OrgUnit:
    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    if unit.tier != OrgTier.SITE:
        raise ValueError("Forecasts are per site, not per area or region")
    return unit


def daily_sales(db: Session, org_unit_id: int, date_from: date, date_to: date) -> dict[date, dict[int, Decimal]]:
    """Item-level sales for one site: {business_date: {menu_item_id: quantity}}.

    Only dates with at least one item line appear. A Sale with no lines
    (no item data for that day) is not a sales day here.
    """
    rows = db.execute(
        select(Sale.sale_date, SaleLine.menu_item_id, func.sum(SaleLine.quantity_sold))
        .join(SaleLine, SaleLine.sale_id == Sale.id)
        .where(
            Sale.location_id == org_unit_id,
            Sale.sale_date >= date_from,
            Sale.sale_date <= date_to,
        )
        .group_by(Sale.sale_date, SaleLine.menu_item_id)
    ).all()
    sales: dict[date, dict[int, Decimal]] = {}
    for day, menu_item_id, quantity in rows:
        sales.setdefault(day, {})[menu_item_id] = _dec(quantity)
    return sales


def history(db: Session, org_unit_id: int, end_date: date, weeks: int = HISTORY_WEEKS) -> dict[date, dict[int, Decimal]]:
    """Daily item-level sales for the trailing `weeks` weeks ending on end_date (inclusive)."""
    start = end_date - timedelta(days=7 * weeks - 1)
    return daily_sales(db, org_unit_id, start, end_date)


def weekday_baseline(hist: dict[date, dict[int, Decimal]], weekday: int) -> dict[int, Decimal]:
    """Mean sold quantity per menu item over the sales days that fall on `weekday`."""
    days = [day for day in hist if day.weekday() == weekday]
    if not days:
        return {}
    totals: dict[int, Decimal] = {}
    for day in days:
        for menu_item_id, quantity in hist[day].items():
            totals[menu_item_id] = totals.get(menu_item_id, ZERO) + quantity
    count = Decimal(len(days))
    return {menu_item_id: total / count for menu_item_id, total in totals.items()}


def effective_recipe_lines(db: Session, menu_item_ids, day: date) -> dict[int, list[RecipeLine]]:
    """Recipe lines in force on `day`, keyed by menu item. valid_from/valid_to null means open."""
    menu_item_ids = list(menu_item_ids)
    if not menu_item_ids:
        return {}
    lines: dict[int, list[RecipeLine]] = {}
    for line in db.execute(
        select(RecipeLine).where(RecipeLine.menu_item_id.in_(menu_item_ids))
    ).scalars():
        if line.valid_from is not None and line.valid_from > day:
            continue
        if line.valid_to is not None and line.valid_to < day:
            continue
        lines.setdefault(line.menu_item_id, []).append(line)
    return lines


def run_forecast(
    db: Session,
    org_unit_id: int,
    start_date: date,
    horizon_days: int = 14,
    *,
    created_by: str | None = None,
    actor: User | None = None,
) -> ForecastRun:
    """Create a forecast run starting on start_date. Refused below 28 sales days of history."""
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}")
    require_site(db, org_unit_id)

    hist = history(db, org_unit_id, start_date - timedelta(days=1))
    if len(hist) < MIN_SALES_DAYS:
        raise ForecastError(
            f"Need {MIN_SALES_DAYS} sales days of item history before {start_date}; found {len(hist)}"
        )

    menu_item_ids = sorted({mid for day in hist.values() for mid in day})
    run = ForecastRun(
        org_unit_id=org_unit_id,
        run_date=start_date,
        method=METHOD,
        horizon_days=horizon_days,
        history_days=len(hist),
        created_by=created_by,
    )
    for offset in range(horizon_days):
        day = start_date + timedelta(days=offset)
        baseline = weekday_baseline(hist, day.weekday())
        for menu_item_id in menu_item_ids:
            run.lines.append(ForecastLine(
                business_date=day,
                menu_item_id=menu_item_id,
                baseline_qty=baseline.get(menu_item_id, ZERO).quantize(QTY),
            ))
    db.add(run)
    db.flush()
    audit_service.record(
        db, actor=actor, actor_name=created_by, entity_type="forecast_run", entity_id=run.id,
        action="create", org_unit_id=org_unit_id, after=audit_service.model_snapshot(run),
        summary=f"Forecast {METHOD} from {start_date} for {horizon_days} day(s), "
                f"{len(menu_item_ids)} menu item(s), {len(hist)} sales day(s) of history",
    )
    db.commit()
    db.refresh(run)
    return run


def adjust_line(
    db: Session,
    line_id: int,
    adjusted_qty,
    note: str | None,
    user: User,
) -> ForecastLine:
    """Set (or, with adjusted_qty=None, clear) a manager override on one forecast line."""
    line = db.get(ForecastLine, line_id)
    if line is None:
        raise LookupError(f"Forecast line {line_id} not found")
    if adjusted_qty is not None and _dec(adjusted_qty) < 0:
        raise ValueError("Adjusted quantity cannot be negative")

    before = {
        "adjusted_qty": _plain_qty(line.adjusted_qty),
        "adjustment_note": line.adjustment_note,
        "effective_qty": _plain_qty(line.effective_qty),
    }
    line.adjusted_qty = _dec(adjusted_qty).quantize(QTY) if adjusted_qty is not None else None
    line.adjustment_note = note
    line.adjusted_by = user.name if adjusted_qty is not None else None
    db.flush()
    after = {
        "adjusted_qty": _plain_qty(line.adjusted_qty),
        "adjustment_note": line.adjustment_note,
        "effective_qty": _plain_qty(line.effective_qty),
    }
    audit_service.record(
        db, actor=user, entity_type="forecast_line", entity_id=line.id, action="adjust",
        org_unit_id=line.forecast_run.org_unit_id, before=before, after=after,
        summary=f"Adjusted forecast for item {line.menu_item_id} on {line.business_date} "
                f"to {after['effective_qty']}",
    )
    db.commit()
    db.refresh(line)
    return line


def _plain_qty(value):
    return str(_dec(value).quantize(QTY)) if value is not None else None


def covering_run(db: Session, org_unit_id: int, start: date, end: date) -> ForecastRun | None:
    """Latest run for the site that starts on or before `start` and covers through `end`."""
    runs = db.execute(
        select(ForecastRun)
        .where(ForecastRun.org_unit_id == org_unit_id, ForecastRun.run_date <= start)
        .order_by(ForecastRun.id.desc())
    ).scalars()
    for run in runs:
        if run.run_date + timedelta(days=run.horizon_days - 1) >= end:
            return run
    return None


def effective_quantities(db: Session, run_id: int, date_from: date, date_to: date) -> dict[tuple[date, int], Decimal]:
    lines = db.execute(
        select(ForecastLine).where(
            ForecastLine.forecast_run_id == run_id,
            ForecastLine.business_date >= date_from,
            ForecastLine.business_date <= date_to,
        )
    ).scalars()
    return {(line.business_date, line.menu_item_id): line.effective_qty for line in lines}


def accuracy(db: Session, org_unit_id: int, days: int = 14, *, as_of: date | None = None) -> dict | None:
    """Forecast accuracy over the `days` days before as_of (as_of itself excluded).

    Compares, for each business date and menu item that has a forecast line
    and falls on a sales day, the effective forecast (from the latest run that
    covers that date) with the posted quantity. Returns None when there is no
    such overlap at all.

    mape: mean of |forecast - actual| / actual over item-days with actual > 0.
    wape: sum of |forecast - actual| / sum of actual over all overlapping item-days.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    as_of = as_of or date.today()
    date_from = as_of - timedelta(days=days)
    date_to = as_of - timedelta(days=1)

    actuals = daily_sales(db, org_unit_id, date_from, date_to)
    if not actuals:
        return None

    lines = db.execute(
        select(ForecastLine)
        .join(ForecastRun, ForecastRun.id == ForecastLine.forecast_run_id)
        .where(
            ForecastRun.org_unit_id == org_unit_id,
            ForecastLine.business_date >= date_from,
            ForecastLine.business_date <= date_to,
        )
        .order_by(ForecastRun.id)
    ).scalars()
    latest: dict[tuple[date, int], Decimal] = {}
    for line in lines:  # ascending run id: a later run replaces an earlier one
        latest[(line.business_date, line.menu_item_id)] = line.effective_qty

    pairs = []
    for (day, menu_item_id), forecast in latest.items():
        if day not in actuals:
            continue
        pairs.append((day, forecast, actuals[day].get(menu_item_id, ZERO)))
    if not pairs:
        return None

    absolute_error = sum((abs(f - a) for _, f, a in pairs), ZERO)
    actual_total = sum((a for _, _, a in pairs), ZERO)
    percentage_errors = [abs(f - a) / a for _, f, a in pairs if a > 0]
    return {
        "window_start": date_from.isoformat(),
        "window_end": date_to.isoformat(),
        "days_compared": len({day for day, _, _ in pairs}),
        "item_days": len(pairs),
        "item_days_with_sales": len(percentage_errors),
        "mape": float(sum(percentage_errors) / len(percentage_errors)) if percentage_errors else None,
        "wape": float(absolute_error / actual_total) if actual_total > 0 else None,
    }
