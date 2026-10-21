"""
Predictive ordering (Feature 4).

suggest_order turns a forecast into a suggested order for one site:

  1. The readiness gate runs first (services/readiness). If any check fails,
     NotReady is raised with the checks, unless override=True. An override needs
     a reason, and it is recorded in the audit log with the failing checks.
  2. The latest forecast run covering today through today+coverage_days is used.
     If none covers that window, a new run is made starting today.
  3. Forecast quantities are exploded through the recipes in force on each
     business date into ingredient requirements. RecipeLine has no yield or
     shrinkage field, so requirements are the recipe quantities as recorded.
  4. On-hand is the existing theoretical stock (spot_check_selector.get_theoretical_stock).
     stock_overrides replace it for this suggestion only and write no StockMovement.
  5. need = max(0, required - on_hand), rounded up to the pack size. The pack size
     is the chosen SupplierItem's pack size, or Item.pack_size if that is unset.
  6. Lines are grouped by supplier: the item's preferred supplier, or the
     supplier_id given. Items with no such supplier are listed as unassigned
     and are not ordered.

Nothing here submits an order. create_draft turns a suggestion into one DRAFT
requisition per supplier through requisition_service.create_draft. A person
reviews those drafts and submits them through the existing approval flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.purchase_order import POStatus, PurchaseOrder, PurchaseOrderLine
from app.models.requisition import Requisition
from app.models.supplier import Supplier, SupplierItem
from app.models.user import User
from app.services import audit_service, requisition_service
from app.services.forecast_service import (
    covering_run, effective_quantities, effective_recipe_lines, require_site, run_forecast,
)
from app.services.readiness import is_ready, readiness
from app.services.requisition_service import LineSpec
from app.services.spot_check_selector import get_theoretical_stock

DEFAULT_HORIZON_DAYS = 14
MAX_COVERAGE_DAYS = 60
QTY = Decimal("0.0001")
ZERO = Decimal(0)
ORDER_HISTORY_DAYS = 28
ENTITY = "predictive_order"


class NotReady(Exception):
    """Readiness checks failed and no override was given."""

    def __init__(self, checks: list[dict]):
        self.checks = checks
        failing = [c["name"] for c in checks if not c["passed"]]
        super().__init__("Readiness checks failed: " + ", ".join(failing))


@dataclass
class SuggestedLine:
    item_id: int
    item_name: str
    supplier_id: int
    required_qty: Decimal
    on_hand_qty: Decimal
    suggested_qty: Decimal
    last_order_qty: Decimal | None
    four_week_avg_order_qty: Decimal


@dataclass
class UnassignedLine:
    item_id: int
    item_name: str
    need_qty: Decimal
    reason: str


@dataclass
class Suggestion:
    org_unit_id: int
    forecast_run_id: int
    coverage_days: int
    delivery_date: date
    as_of: date
    readiness: list[dict]
    overridden: bool
    override_reason: str | None
    stock_overrides_applied: list[int]
    lines: list[SuggestedLine] = field(default_factory=list)
    unassigned: list[UnassignedLine] = field(default_factory=list)

    def by_supplier(self) -> dict[int, list[SuggestedLine]]:
        groups: dict[int, list[SuggestedLine]] = {}
        for line in self.lines:
            groups.setdefault(line.supplier_id, []).append(line)
        return groups


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _preferred_link(db: Session, item_id: int) -> SupplierItem | None:
    return db.execute(
        select(SupplierItem)
        .join(Supplier, Supplier.id == SupplierItem.supplier_id)
        .where(
            SupplierItem.item_id == item_id,
            SupplierItem.is_preferred.is_(True),
            SupplierItem.is_active.is_(True),
            Supplier.is_active.is_(True),
        )
        .order_by(SupplierItem.id)
        .limit(1)
    ).scalar_one_or_none()


def _supplier_link(db: Session, item_id: int, supplier_id: int) -> SupplierItem | None:
    return db.execute(
        select(SupplierItem)
        .where(
            SupplierItem.item_id == item_id,
            SupplierItem.supplier_id == supplier_id,
            SupplierItem.is_active.is_(True),
        )
        .order_by(SupplierItem.id)
        .limit(1)
    ).scalar_one_or_none()


def _order_history(db: Session, org_unit_id: int, item_ids: list[int], as_of: date):
    """Per item: (last order quantity, mean order quantity over the last 28 days)."""
    rows = db.execute(
        select(PurchaseOrderLine.item_id, PurchaseOrder.order_date, PurchaseOrderLine.id,
               PurchaseOrderLine.quantity_ordered)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrder.location_id == org_unit_id,
            PurchaseOrder.status != POStatus.CANCELLED,
            PurchaseOrder.order_date <= as_of,
            PurchaseOrderLine.item_id.in_(item_ids),
        )
    ).all()
    latest: dict[int, tuple[date, int, Decimal]] = {}
    recent: dict[int, list[Decimal]] = {}
    window_start = as_of - timedelta(days=ORDER_HISTORY_DAYS)
    for item_id, order_date, line_id, quantity in rows:
        key = (order_date, line_id)
        if item_id not in latest or key > latest[item_id][:2]:
            latest[item_id] = (order_date, line_id, _dec(quantity))
        if order_date >= window_start:
            recent.setdefault(item_id, []).append(_dec(quantity))
    last = {item_id: value[2] for item_id, value in latest.items()}
    average = {
        item_id: sum(quantities, ZERO) / len(quantities)
        for item_id, quantities in recent.items()
    }
    return last, average


def suggest_order(
    db: Session,
    org_unit_id: int,
    coverage_days: int,
    delivery_date: date,
    *,
    supplier_id: int | None = None,
    stock_overrides: dict[int, float] | None = None,
    override: bool = False,
    override_reason: str | None = None,
    as_of: date | None = None,
    actor: User | None = None,
) -> Suggestion:
    """Compute a suggested order. Raises NotReady when the readiness gate fails and override is False."""
    as_of = as_of or date.today()
    if not 1 <= coverage_days <= MAX_COVERAGE_DAYS:
        raise ValueError(f"coverage_days must be between 1 and {MAX_COVERAGE_DAYS}")
    require_site(db, org_unit_id)
    if supplier_id is not None and db.get(Supplier, supplier_id) is None:
        raise LookupError(f"Supplier {supplier_id} not found")

    reason = (override_reason or "").strip() or None
    if override and reason is None:
        raise ValueError("An override needs a reason")
    overrides = {int(item_id): _dec(qty) for item_id, qty in (stock_overrides or {}).items()}
    if any(qty < 0 for qty in overrides.values()):
        raise ValueError("Stock overrides cannot be negative")

    checks = readiness(db, org_unit_id, as_of)
    overridden = False
    if not is_ready(checks):
        if not override:
            raise NotReady(checks)
        overridden = True

    window_end = as_of + timedelta(days=coverage_days)
    run = covering_run(db, org_unit_id, as_of, window_end)
    if run is None:
        run = run_forecast(
            db, org_unit_id, as_of, max(DEFAULT_HORIZON_DAYS, coverage_days + 1),
            created_by=actor.name if actor is not None else None, actor=actor,
        )

    # Explode forecast quantities through the recipes in force on each business date.
    quantities = effective_quantities(db, run.id, as_of, window_end)
    by_day: dict[date, dict[int, Decimal]] = {}
    for (day, menu_item_id), qty in quantities.items():
        if qty > 0:
            by_day.setdefault(day, {})[menu_item_id] = qty
    required: dict[int, Decimal] = {}
    for day, day_items in by_day.items():
        recipes = effective_recipe_lines(db, day_items.keys(), day)
        for menu_item_id, qty in day_items.items():
            for line in recipes.get(menu_item_id, []):
                required[line.item_id] = required.get(line.item_id, ZERO) + qty * _dec(line.quantity_used)

    items = {
        item.id: item
        for item in db.execute(select(Item).where(Item.id.in_(list(required)))).scalars()
    } if required else {}

    lines: list[SuggestedLine] = []
    unassigned: list[UnassignedLine] = []
    applied: list[int] = []
    for item_id in sorted(required):
        item = items[item_id]
        required_qty = required[item_id].quantize(QTY)
        if item_id in overrides:
            on_hand = overrides[item_id]
            applied.append(item_id)
        else:
            on_hand = _dec(get_theoretical_stock(db, org_unit_id, item_id))
        need = max(ZERO, required_qty - on_hand)
        if need <= 0:
            continue

        if supplier_id is not None:
            link = _supplier_link(db, item_id, supplier_id)
            reason_text = "not supplied by the selected supplier"
        else:
            link = _preferred_link(db, item_id)
            reason_text = "no preferred supplier"
        if link is None:
            unassigned.append(UnassignedLine(item_id, item.name, need.quantize(QTY), reason_text))
            continue

        pack = _dec(link.pack_size)
        if pack <= 0:
            pack = _dec(item.pack_size)
        if pack <= 0:
            pack = Decimal(1)
        suggested = ((need / pack).to_integral_value(rounding=ROUND_CEILING) * pack).quantize(QTY)
        lines.append(SuggestedLine(
            item_id=item_id, item_name=item.name, supplier_id=link.supplier_id,
            required_qty=required_qty, on_hand_qty=on_hand.quantize(QTY),
            suggested_qty=suggested, last_order_qty=None, four_week_avg_order_qty=ZERO,
        ))

    if lines:
        last, average = _order_history(db, org_unit_id, [l.item_id for l in lines], as_of)
        for line in lines:
            line.last_order_qty = last.get(line.item_id)
            line.four_week_avg_order_qty = average.get(line.item_id, ZERO).quantize(QTY)

    lines.sort(key=lambda l: (l.supplier_id, l.item_id))
    suggestion = Suggestion(
        org_unit_id=org_unit_id,
        forecast_run_id=run.id,
        coverage_days=coverage_days,
        delivery_date=delivery_date,
        as_of=as_of,
        readiness=checks,
        overridden=overridden,
        override_reason=reason if overridden else None,
        stock_overrides_applied=applied,
        lines=lines,
        unassigned=unassigned,
    )

    if overridden:
        failing = [c for c in checks if not c["passed"]]
        audit_service.record(
            db, actor=actor, entity_type=ENTITY, entity_id=run.id, action="override",
            org_unit_id=org_unit_id,
            after={"reason": reason, "failing_checks": failing, "coverage_days": coverage_days,
                   "delivery_date": delivery_date.isoformat(), "forecast_run_id": run.id},
            summary=f"Predictive order gate overridden: {', '.join(c['name'] for c in failing)}",
        )
        db.commit()
    return suggestion


def create_draft(
    db: Session,
    suggestion: Suggestion,
    requested_by: str,
    *,
    actor: User | None = None,
) -> list[Requisition]:
    """Create one DRAFT requisition per supplier. Never submits."""
    groups = suggestion.by_supplier()
    if not groups:
        return []
    requisitions: list[Requisition] = []
    for supplier_id, lines in groups.items():
        requisitions.append(requisition_service.create_draft(
            db,
            org_unit_id=suggestion.org_unit_id,
            lines=[LineSpec(item_id=line.item_id, quantity=line.suggested_qty) for line in lines],
            supplier_id=supplier_id,
            needed_by=suggestion.delivery_date,
            notes=f"Suggested by forecast run {suggestion.forecast_run_id}",
            requested_by=requested_by,
            actor=actor,
        ))
    audit_service.record(
        db, actor=actor, actor_name=requested_by, entity_type=ENTITY,
        entity_id=suggestion.forecast_run_id, action="create_drafts",
        org_unit_id=suggestion.org_unit_id,
        after={"requisitions": [r.requisition_number for r in requisitions]},
        summary=f"Created {len(requisitions)} draft requisition(s) from forecast run "
                f"{suggestion.forecast_run_id}: {', '.join(r.requisition_number for r in requisitions)}",
    )
    db.commit()
    return requisitions
