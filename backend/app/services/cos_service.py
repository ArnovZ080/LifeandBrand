"""
Cost-of-Sales variance engine (Phase 2).

Actual usage per item comes from the usage equation over real stock data;
theoretical usage comes from recipes x POS sales. The gap, valued at item
unit cost, drives CosFlag rows for review.

Data sources used (see docstrings for per-source assumptions):
  - SpotCheckItem counts        → opening / closing quantities
  - DeliveryLine                → receipts
  - StockMovement TRANSFER_IN / TRANSFER_OUT → transfers
  - RecipeLine x SaleLine       → theoretical usage
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_subtree_ids
from app.config import settings
from app.models import (
    Delivery, DeliveryLine, Item, MenuItem, OrgUnit, RecipeLine, Sale, SaleLine,
    SpotCheckItem, SpotCheckSession, StockMovement,
)
from app.models.cos_flag import CosFlag
from app.models.location import OrgTier
from app.models.stock import MovementType
from app.services.net_sales import net_sales


def period_bounds(period: str) -> tuple[date, date]:
    """'YYYY-MM' → (first day, last day) of that month."""
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _unit_ids(db: Session, org_unit_id: int) -> list[int]:
    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        return []
    return [unit.id] if unit.tier == OrgTier.SITE else get_subtree_ids(db, unit.id)


def usage_equation(
    opening,
    receipts,
    transfers_in,
    transfers_out,
    yield_in,
    yield_out,
    closing,
) -> Decimal:
    """Actual usage = opening + receipts + transfers_in - transfers_out
                      + yield_in - yield_out - closing.

    All inputs are treated as Decimal (None → 0). Positive result = stock
    consumed over the window.
    """
    d = lambda v: Decimal(str(v)) if v is not None else Decimal(0)  # noqa: E731
    return (d(opening) + d(receipts) + d(transfers_in) - d(transfers_out)
            + d(yield_in) - d(yield_out) - d(closing))


def _latest_counts(db: Session, unit_ids: list[int], on_or_before: date,
                   on_or_after: date | None = None) -> dict[int, float]:
    """Latest counted SpotCheckItem.actual_quantity per item at these units,
    with session_date <= on_or_before (and >= on_or_after when given)."""
    q = (
        select(SpotCheckItem.item_id, SpotCheckItem.actual_quantity, SpotCheckSession.session_date)
        .join(SpotCheckSession, SpotCheckItem.session_id == SpotCheckSession.id)
        .where(
            SpotCheckSession.location_id.in_(unit_ids),
            SpotCheckSession.session_date <= on_or_before,
            SpotCheckItem.actual_quantity.is_not(None),
        )
        .order_by(SpotCheckSession.session_date.asc())
    )
    if on_or_after is not None:
        q = q.where(SpotCheckSession.session_date >= on_or_after)
    counts: dict[int, float] = {}
    for item_id, qty, _session_date in db.execute(q):
        counts[item_id] = float(qty)  # later dates overwrite earlier ones
    return counts


def actual_usage(db: Session, org_unit_id: int, period: str) -> dict[int, Decimal]:
    """Actual usage quantity per item_id for the period, via the usage equation.

    Assumptions (dictated by the data actually captured today):
      - opening stock  = the latest spot-check count on/before the period start
        (spot checks are the only physical counts in the schema);
      - closing stock  = the latest spot-check count within the period;
      - receipts       = sum of DeliveryLine quantity_accepted (falling back to
        quantity_delivered) for deliveries dated in the period;
      - transfers      = StockMovement TRANSFER_IN / TRANSFER_OUT rows in the
        period (quantity stored positive-in / negative-out; abs() is used);
      - yield in/out   = no data source yet → 0.

    Items without BOTH an opening and a closing count are omitted — the
    equation cannot be anchored for them.
    """
    start, end = period_bounds(period)
    unit_ids = _unit_ids(db, org_unit_id)
    if not unit_ids:
        return {}

    opening = _latest_counts(db, unit_ids, on_or_before=start)
    closing = _latest_counts(db, unit_ids, on_or_before=end, on_or_after=start)

    receipts: dict[int, Decimal] = {}
    rows = db.execute(
        select(DeliveryLine.item_id,
               func.sum(func.coalesce(DeliveryLine.quantity_accepted,
                                      DeliveryLine.quantity_delivered)))
        .join(Delivery, DeliveryLine.delivery_id == Delivery.id)
        .where(Delivery.location_id.in_(unit_ids),
               Delivery.delivery_date >= start,
               Delivery.delivery_date <= end)
        .group_by(DeliveryLine.item_id)
    )
    for item_id, qty in rows:
        receipts[item_id] = Decimal(str(qty or 0))

    transfers: dict[int, dict[str, Decimal]] = {}
    rows = db.execute(
        select(StockMovement.item_id, StockMovement.movement_type,
               func.sum(StockMovement.quantity))
        .where(StockMovement.location_id.in_(unit_ids),
               StockMovement.movement_type.in_([MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT]),
               func.date(StockMovement.created_at) >= start,
               func.date(StockMovement.created_at) <= end)
        .group_by(StockMovement.item_id, StockMovement.movement_type)
    )
    for item_id, mtype, qty in rows:
        transfers.setdefault(item_id, {})[mtype.value] = abs(Decimal(str(qty or 0)))

    usage: dict[int, Decimal] = {}
    for item_id in set(opening) & set(closing):
        t = transfers.get(item_id, {})
        usage[item_id] = usage_equation(
            opening=opening[item_id],
            receipts=receipts.get(item_id, 0),
            transfers_in=t.get("transfer_in", 0),
            transfers_out=t.get("transfer_out", 0),
            yield_in=0,
            yield_out=0,
            closing=closing[item_id],
        )
    return usage


def theoretical_usage(db: Session, org_unit_id: int, period: str) -> dict[int, Decimal]:
    """Theoretical usage per item_id: sum of recipe_line.quantity_used x
    quantity_sold over every sale line in the period, counting only recipe
    lines whose validity range (valid_from/valid_to, nulls = open-ended)
    covers the sale date."""
    start, end = period_bounds(period)
    unit_ids = _unit_ids(db, org_unit_id)
    if not unit_ids:
        return {}

    rows = db.execute(
        select(RecipeLine.item_id,
               func.sum(RecipeLine.quantity_used * SaleLine.quantity_sold))
        .select_from(SaleLine)
        .join(Sale, SaleLine.sale_id == Sale.id)
        .join(MenuItem, SaleLine.menu_item_id == MenuItem.id)
        .join(RecipeLine, RecipeLine.menu_item_id == MenuItem.id)
        .where(
            Sale.location_id.in_(unit_ids),
            Sale.sale_date >= start,
            Sale.sale_date <= end,
            (RecipeLine.valid_from.is_(None)) | (RecipeLine.valid_from <= Sale.sale_date),
            (RecipeLine.valid_to.is_(None)) | (RecipeLine.valid_to >= Sale.sale_date),
        )
        .group_by(RecipeLine.item_id)
    )
    return {item_id: Decimal(str(qty or 0)) for item_id, qty in rows}


def compute_variance(db: Session, org_unit_id: int, period: str) -> dict:
    """Compute the COS variance summary for an org unit + period, and
    create/update CosFlag rows for items whose |variance value| exceeds
    settings.cos_flag_threshold_value.

    Returns {"summary": {...}, "flags": [CosFlag, ...]} where flags are ALL
    stored flags for the unit/period (including previously dismissed ones).
    Existing dismissed flags keep their status; open flags get refreshed
    quantities and a (re)classified cause.
    """
    from app.services.cos_classifier import build_context, classify

    actual = actual_usage(db, org_unit_id, period)
    theoretical = theoretical_usage(db, org_unit_id, period)

    item_ids = set(actual) | set(theoretical)
    items = {
        i.id: i
        for i in db.execute(select(Item).where(Item.id.in_(item_ids))).scalars()
    } if item_ids else {}

    def value(qty: Decimal | None, item: Item | None) -> Decimal | None:
        if qty is None or item is None or item.unit_cost is None:
            return None
        return (qty * Decimal(str(item.unit_cost))).quantize(Decimal("0.01"))

    actual_value = Decimal(0)
    theoretical_value = Decimal(0)
    threshold = Decimal(str(settings.cos_flag_threshold_value))

    for item_id in item_ids:
        item = items.get(item_id)
        av = value(actual.get(item_id), item)
        tv = value(theoretical.get(item_id), item)
        if av is not None:
            actual_value += av
        if tv is not None:
            theoretical_value += tv

        # Flag only items where both sides are known and valued
        if av is None or tv is None:
            continue
        variance_qty = actual[item_id] - theoretical[item_id]
        variance_value = av - tv
        if abs(variance_value) <= threshold:
            continue

        flag = db.execute(
            select(CosFlag).where(
                CosFlag.org_unit_id == org_unit_id,
                CosFlag.item_id == item_id,
                CosFlag.period == period,
            )
        ).scalars().first()
        if flag is None:
            flag = CosFlag(org_unit_id=org_unit_id, item_id=item_id, period=period)
            db.add(flag)
        flag.actual_qty = actual[item_id]
        flag.theoretical_qty = theoretical[item_id]
        flag.variance_qty = variance_qty
        flag.variance_value = variance_value
        db.flush()

    # Classify open flags for the period (needs all sibling flags flushed first)
    period_flags = db.execute(
        select(CosFlag).where(CosFlag.org_unit_id == org_unit_id, CosFlag.period == period)
    ).scalars().all()
    for flag in period_flags:
        if flag.status == "open":
            flag.cause = classify(flag, build_context(db, flag))
    db.commit()

    net = net_sales(db, org_unit_id, *period_bounds(period), level="L2")

    def pct(v: Decimal) -> float | None:
        if net is None or net == 0:
            return None
        return round(float(v / net * 100), 2)

    actual_cos_pct = pct(actual_value)
    theoretical_cos_pct = pct(theoretical_value)
    summary = {
        "actual_cos_pct": actual_cos_pct,
        "theoretical_cos_pct": theoretical_cos_pct,
        "variance_pct": (
            round(actual_cos_pct - theoretical_cos_pct, 2)
            if actual_cos_pct is not None and theoretical_cos_pct is not None else None
        ),
        "actual_usage_value": float(actual_value),
        "theoretical_usage_value": float(theoretical_value),
    }
    return {"summary": summary, "flags": period_flags}
