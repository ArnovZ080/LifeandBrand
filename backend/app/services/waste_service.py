"""
Wastage logging and reporting (Feature 1).

log_waste writes a WasteEvent and a negative StockMovement (movement_type
WASTE, reference_type "waste_event") in the same transaction. The cost is
snapshotted from Item.unit_cost at logging time.

Org units are aggregated over their whole subtree (get_subtree_ids), so an
AREA-level summary includes all of its sites.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_subtree_ids
from app.models import Item, OrgUnit
from app.models.stock import MovementType, StockMovement
from app.models.user import User
from app.models.waste import WasteEvent, WasteReason
from app.services import audit_service

CENT = Decimal("0.01")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def log_waste(
    db: Session,
    *,
    org_unit_id: int,
    item_id: int,
    quantity,
    reason: WasteReason,
    reason_note: str | None = None,
    logged_by: str | None = None,
    event_date: date | None = None,
    actor: User | None = None,
) -> WasteEvent:
    """Record a waste event and post the matching stock movement.

    Raises LookupError for an unknown org unit or item and ValueError for a
    non-positive quantity. The audit row is written in the same commit.
    """
    qty = _dec(quantity)
    if qty <= 0:
        raise ValueError("Waste quantity must be positive")
    if db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    item = db.get(Item, item_id)
    if item is None:
        raise LookupError(f"Item {item_id} not found")

    unit_cost = item.unit_cost  # snapshot — later Item.unit_cost edits do not restate waste
    cost_value = (qty * _dec(unit_cost)).quantize(CENT) if unit_cost is not None else Decimal("0.00")

    event = WasteEvent(
        org_unit_id=org_unit_id,
        item_id=item_id,
        quantity=qty,
        reason=reason,
        reason_note=reason_note,
        unit_cost=unit_cost,
        cost_value=cost_value,
        logged_by=logged_by,
        event_date=event_date or date.today(),
    )
    db.add(event)
    db.flush()  # need event.id for the movement reference

    db.add(StockMovement(
        location_id=org_unit_id,
        item_id=item_id,
        movement_type=MovementType.WASTE,
        quantity=-qty,
        unit_cost=unit_cost,
        reference_id=event.id,
        reference_type="waste_event",
        notes=f"waste: {reason.value}",
        created_by=logged_by,
    ))
    audit_service.record(
        db, actor=actor, actor_name=logged_by,
        entity_type="waste_event", entity_id=event.id, action="create",
        org_unit_id=org_unit_id, after=audit_service.model_snapshot(event),
        summary=f"Logged waste: {qty} of item {item.code} ({reason.value})",
    )
    db.commit()
    db.refresh(event)
    return event


def waste_summary(db: Session, org_unit_id: int, date_from: date, date_to: date) -> dict:
    """Waste totals for an org unit subtree over [date_from, date_to].

    Returns:
        {
          "events": int,
          "total_cost_value": Decimal,
          "by_reason": [{"reason", "events", "quantity", "cost_value"}, ...],
          "by_item":   [{"item_id", "item_name", "quantity", "cost_value"}, ...]
                        sorted by cost_value descending,
        }
    """
    unit_ids = get_subtree_ids(db, org_unit_id)
    window = [
        WasteEvent.org_unit_id.in_(unit_ids),
        WasteEvent.event_date >= date_from,
        WasteEvent.event_date <= date_to,
    ]

    events, total_cost = db.execute(
        select(func.count(WasteEvent.id), func.sum(WasteEvent.cost_value)).where(*window)
    ).one()

    by_reason = []
    reason_rows = db.execute(
        select(
            WasteEvent.reason,
            func.count(WasteEvent.id),
            func.sum(WasteEvent.quantity),
            func.sum(WasteEvent.cost_value),
        )
        .where(*window)
        .group_by(WasteEvent.reason)
        .order_by(func.sum(WasteEvent.cost_value).desc())
    ).all()
    for reason, count, qty, cost in reason_rows:
        by_reason.append({
            "reason": reason.value,
            "events": int(count),
            "quantity": _dec(qty),
            "cost_value": _dec(cost),
        })

    by_item = []
    item_rows = db.execute(
        select(
            WasteEvent.item_id,
            Item.name,
            func.sum(WasteEvent.quantity),
            func.sum(WasteEvent.cost_value),
        )
        .join(Item, Item.id == WasteEvent.item_id)
        .where(*window)
        .group_by(WasteEvent.item_id, Item.name)
        .order_by(func.sum(WasteEvent.cost_value).desc())
    ).all()
    for item_id, name, qty, cost in item_rows:
        by_item.append({
            "item_id": item_id,
            "item_name": name,
            "quantity": _dec(qty),
            "cost_value": _dec(cost),
        })

    return {
        "events": int(events or 0),
        "total_cost_value": _dec(total_cost),
        "by_reason": by_reason,
        "by_item": by_item,
    }


def period_waste_value(db: Session, org_unit_id: int, start: date, end: date) -> Decimal:
    """Total waste cost value logged for the org unit subtree in [start, end]."""
    unit_ids = get_subtree_ids(db, org_unit_id)
    total = db.execute(
        select(func.sum(WasteEvent.cost_value)).where(
            WasteEvent.org_unit_id.in_(unit_ids),
            WasteEvent.event_date >= start,
            WasteEvent.event_date <= end,
        )
    ).scalar()
    return _dec(total)
