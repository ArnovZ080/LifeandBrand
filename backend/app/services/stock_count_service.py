"""
Full stock counts and variance (Feature 1).

Lifecycle of a StockCount:
  create_count  → one line per item, system_qty snapshotted from on-hand
  record_counts → counted_qty / counted_by / counted_at per line (repeatable)
  submit_count  → refuses while any line is uncounted; otherwise computes
                  variance_qty = counted - system, variance_value = variance_qty
                  x unit_cost, posts ADJUSTMENT StockMovements and closes the count.

On-hand is the existing calculation in spot_check_selector.get_theoretical_stock
(net sum of StockMovement quantity at the site).

Counts are taken per SITE: stock movements are posted to a single location, so
an AREA-level on-hand has no meaning. Create_count rejects non-SITE units.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_subtree_ids
from app.models import Item, OrgUnit
from app.models.location import OrgTier
from app.models.stock import MovementType, StockMovement
from app.models.stock_count import CountTemplate, StockCount, StockCountLine, StockCountStatus
from app.services.spot_check_selector import get_theoretical_stock

CENT = Decimal("0.01")
QTY = Decimal("0.0001")
TOP_N = 10


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _qty(value) -> Decimal:
    return _dec(value).quantize(QTY)


def _unique_ordered(item_ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item_id in item_ids:
        if item_id not in seen:
            seen.add(item_id)
            out.append(item_id)
    return out


def _require_items(db: Session, item_ids: list[int]) -> dict[int, Item]:
    items = {i.id: i for i in db.execute(select(Item).where(Item.id.in_(item_ids))).scalars()}
    missing = [i for i in item_ids if i not in items]
    if missing:
        raise LookupError(f"Items not found: {missing}")
    return items


def create_template(
    db: Session,
    *,
    name: str,
    item_ids: list[int],
    org_unit_id: int | None = None,
) -> CountTemplate:
    """Save an ordered list of items as a reusable count route."""
    ordered = _unique_ordered(item_ids)
    if not ordered:
        raise ValueError("A count template needs at least one item")
    _require_items(db, ordered)
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    template = CountTemplate(name=name, org_unit_id=org_unit_id, item_ids=ordered)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def create_count(
    db: Session,
    *,
    org_unit_id: int,
    name: str,
    count_date: date,
    template_id: int | None = None,
    item_ids: list[int] | None = None,
    created_by: str | None = None,
) -> StockCount:
    """Open a full count for a site. Give exactly one of template_id or item_ids."""
    if (template_id is None) == (item_ids is None):
        raise ValueError("Provide exactly one of template_id or item_ids")

    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    if unit.tier != OrgTier.SITE:
        raise ValueError("Stock counts are taken per site, not per area or region")

    if template_id is not None:
        template = db.get(CountTemplate, template_id)
        if template is None:
            raise LookupError(f"Count template {template_id} not found")
        if template.org_unit_id is not None and template.org_unit_id != org_unit_id:
            raise ValueError("Count template belongs to a different site")
        ordered = _unique_ordered(list(template.item_ids))
    else:
        ordered = _unique_ordered(item_ids or [])
        if not ordered:
            raise ValueError("A count needs at least one item")

    items = _require_items(db, ordered)

    count = StockCount(
        org_unit_id=org_unit_id,
        template_id=template_id,
        name=name,
        count_date=count_date,
        status=StockCountStatus.OPEN,
        created_by=created_by,
    )
    db.add(count)
    db.flush()

    for item_id in ordered:
        item = items[item_id]
        db.add(StockCountLine(
            stock_count_id=count.id,
            item_id=item_id,
            system_qty=_qty(get_theoretical_stock(db, org_unit_id, item_id)),
            unit_cost=item.unit_cost,
        ))

    db.commit()
    db.refresh(count)
    return count


def _get_count(db: Session, count_id: int) -> StockCount:
    count = db.get(StockCount, count_id)
    if count is None:
        raise LookupError(f"Stock count {count_id} not found")
    return count


def record_counts(db: Session, count_id: int, lines: list[dict]) -> StockCount:
    """Record counted quantities. Each dict: item_id, counted_qty, optional
    counted_by and notes. Can be called repeatedly until the count is submitted."""
    count = _get_count(db, count_id)
    if count.status != StockCountStatus.OPEN:
        raise ValueError("Stock count is already submitted")

    by_item = {line.item_id: line for line in count.lines}
    now = datetime.utcnow()
    for entry in lines:
        line = by_item.get(entry["item_id"])
        if line is None:
            raise ValueError(f"Item {entry['item_id']} is not on this count")
        counted = _dec(entry["counted_qty"])
        if counted < 0:
            raise ValueError(f"Counted quantity for item {entry['item_id']} cannot be negative")
        line.counted_qty = _qty(counted)
        line.counted_by = entry.get("counted_by") or line.counted_by
        line.counted_at = now
        if entry.get("notes") is not None:
            line.notes = entry["notes"]

    db.commit()
    db.refresh(count)
    return count


def submit_count(db: Session, count_id: int) -> StockCount:
    """Finalise a count and post the adjustments.

    Refuses (ValueError) while any line has no counted quantity.
    variance_qty = counted - system (stored on the line and used for
    variance_value). The adjustment posted to stock is counted - current
    on-hand at submission, so on-hand equals the counted quantity even if
    movements were posted after the count was created. The two are equal
    when nothing moved in between.
    """
    count = _get_count(db, count_id)
    if count.status != StockCountStatus.OPEN:
        raise ValueError("Stock count is already submitted")

    uncounted = [line.item_id for line in count.lines if line.counted_qty is None]
    if uncounted:
        raise ValueError(f"Count has uncounted lines for items: {uncounted}")

    now = datetime.utcnow()
    for line in count.lines:
        counted = _dec(line.counted_qty)
        system = _dec(line.system_qty)
        variance_qty = (counted - system).quantize(QTY)
        unit_cost = line.unit_cost
        variance_value = (
            (variance_qty * _dec(unit_cost)).quantize(CENT) if unit_cost is not None else Decimal("0.00")
        )
        line.variance_qty = variance_qty
        line.variance_value = variance_value

        live = _qty(get_theoretical_stock(db, count.org_unit_id, line.item_id))
        adjustment = (counted - live).quantize(QTY)
        if adjustment != 0:
            db.add(StockMovement(
                location_id=count.org_unit_id,
                item_id=line.item_id,
                movement_type=MovementType.ADJUSTMENT,
                quantity=adjustment,
                unit_cost=unit_cost,
                reference_id=count.id,
                reference_type="stock_count",
                notes=f"stock count '{count.name}' adjustment",
                created_by=line.counted_by or count.created_by,
            ))

    count.status = StockCountStatus.SUBMITTED
    count.submitted_at = now
    db.commit()
    db.refresh(count)
    return count


def _submitted_lines(unit_ids: list[int], date_from: date, date_to: date):
    return (
        select(StockCountLine.item_id, Item.name, StockCountLine.variance_qty,
               StockCountLine.variance_value)
        .join(StockCount, StockCount.id == StockCountLine.stock_count_id)
        .join(Item, Item.id == StockCountLine.item_id)
        .where(
            StockCount.org_unit_id.in_(unit_ids),
            StockCount.status == StockCountStatus.SUBMITTED,
            StockCount.count_date >= date_from,
            StockCount.count_date <= date_to,
        )
    )


def count_variance_summary(db: Session, org_unit_id: int, date_from: date, date_to: date) -> dict:
    """Submitted-count variance for an org unit subtree over [date_from, date_to].

    Sign convention: negative variance = stock found short of the system figure.

    Returns:
        {
          "counts": int,                       # submitted counts in the window
          "total_variance_value": Decimal,
          "top_items": [{"item_id", "item_name", "variance_qty", "variance_value"}]
                       top 10 by absolute variance_value
        }
    """
    unit_ids = get_subtree_ids(db, org_unit_id)
    counts = db.execute(
        select(func.count(StockCount.id)).where(
            StockCount.org_unit_id.in_(unit_ids),
            StockCount.status == StockCountStatus.SUBMITTED,
            StockCount.count_date >= date_from,
            StockCount.count_date <= date_to,
        )
    ).scalar()

    per_item: dict[int, dict] = {}
    for item_id, name, qty, value in db.execute(_submitted_lines(unit_ids, date_from, date_to)):
        row = per_item.setdefault(item_id, {
            "item_id": item_id, "item_name": name,
            "variance_qty": Decimal(0), "variance_value": Decimal(0),
        })
        row["variance_qty"] += _dec(qty)
        row["variance_value"] += _dec(value)

    total = sum((row["variance_value"] for row in per_item.values()), Decimal(0))
    movers = [r for r in per_item.values() if r["variance_qty"] != 0]
    top = sorted(movers, key=lambda r: abs(r["variance_value"]), reverse=True)[:TOP_N]
    return {
        "counts": int(counts or 0),
        "total_variance_value": total,
        "top_items": top,
    }


def period_count_variance(db: Session, org_unit_id: int, start: date, end: date) -> Decimal:
    """Sum of submitted-count variance_value for the org unit subtree in [start, end]."""
    unit_ids = get_subtree_ids(db, org_unit_id)
    total = db.execute(
        select(func.sum(StockCountLine.variance_value))
        .join(StockCount, StockCount.id == StockCountLine.stock_count_id)
        .where(
            StockCount.org_unit_id.in_(unit_ids),
            StockCount.status == StockCountStatus.SUBMITTED,
            StockCount.count_date >= start,
            StockCount.count_date <= end,
        )
    ).scalar()
    return _dec(total)
