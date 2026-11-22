"""Per-venue par levels and the shopping list.

Rule-based reordering, separate from the forecast and predictive ordering code.

  shopping_list  -> for each active par at a site, the stock position is on-hand
                    plus quantity already on order (open requisitions and the
                    unreceived part of open purchase orders). When the position
                    is at or below the reorder point, the shortfall to par is
                    rounded up to a whole pack and grouped by the item's
                    preferred supplier. Items with no preferred supplier are
                    listed as unassigned and are not ordered.
  create_draft_requisitions -> one DRAFT requisition per supplier group, staged with
                    requisition_service.stage_draft in a single transaction (all or
                    nothing). Nothing is submitted here.

Pack size: the preferred SupplierItem's pack size when it is set and above zero,
else Item.pack_size, else 1.
Price: requisition_service.current_unit_price (catalogue, then Item.unit_cost).
Only site org units hold par levels; area and higher units are refused.

Every par change and every draft creation writes an audit event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Item, OrgTier, OrgUnit, Supplier, SupplierItem
from app.models.par_level import ParLevel
from app.models.purchase_order import POStatus, PurchaseOrder, PurchaseOrderLine
from app.models.requisition import Requisition, RequisitionLine, RequisitionStatus
from app.models.user import User
from app.services import audit_service, requisition_service
from app.services.approval_service import ConflictError
from app.services.requisition_service import LineSpec
from app.services.spot_check_selector import get_theoretical_stock

ENTITY = "par_level"
SHOPPING_ENTITY = "shopping_list"
QTY = Decimal("0.0001")
ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass
class ShoppingLine:
    item_id: int
    item_name: str
    unit: str
    on_hand_qty: Decimal
    par_qty: Decimal
    reorder_point: Decimal
    order_qty: Decimal
    estimated_unit_price: Decimal | None
    estimated_value: Decimal | None
    on_order_qty: Decimal = ZERO


@dataclass
class SupplierGroup:
    supplier_id: int
    supplier_name: str
    lines: list[ShoppingLine] = field(default_factory=list)

    @property
    def total_estimated_value(self) -> Decimal:
        return sum((l.estimated_value for l in self.lines if l.estimated_value is not None), ZERO)


@dataclass
class ShoppingList:
    org_unit_id: int
    generated_at: datetime
    groups: list[SupplierGroup]
    unassigned: list[ShoppingLine]


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _site(db: Session, org_unit_id: int) -> OrgUnit:
    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    if unit.tier != OrgTier.SITE:
        raise ValueError("Par levels and shopping lists apply to site org units only")
    return unit


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Conflicting record was written concurrently; please retry") from exc


# ── Par levels ────────────────────────────────────────────────────────────────

def upsert_par(
    db: Session,
    org_unit: OrgUnit,
    item_id: int,
    par_qty,
    reorder_point,
    user: User,
) -> ParLevel:
    """Create or update the par for one item at one site. Reactivates a removed par."""
    if org_unit.tier != OrgTier.SITE:
        raise ValueError("Par levels apply to site org units only")
    par, reorder = _dec(par_qty), _dec(reorder_point)
    if par <= 0:
        raise ValueError("Par quantity must be greater than zero")
    if reorder < 0:
        raise ValueError("Reorder point cannot be negative")
    if reorder >= par:
        raise ValueError("Reorder point must be less than par quantity")
    if db.get(Item, item_id) is None:
        raise LookupError(f"Item {item_id} not found")

    row = db.execute(
        select(ParLevel).where(ParLevel.org_unit_id == org_unit.id, ParLevel.item_id == item_id)
    ).scalar_one_or_none()

    if row is None:
        row = ParLevel(org_unit_id=org_unit.id, item_id=item_id)
        db.add(row)
        action = "create"
        before_snap = None
    else:
        action = "update"
        before_snap = audit_service.model_snapshot(row)

    row.par_qty = par.quantize(QTY)
    row.reorder_point = reorder.quantize(QTY)
    row.active = True
    row.updated_by = user.name
    db.flush()

    after_snap = audit_service.model_snapshot(row)
    if before_snap is None:
        before_out, after_out = None, after_snap
    else:
        before_out, after_out = audit_service.diff(before_snap, after_snap)
    audit_service.record(
        db, actor=user, entity_type=ENTITY, entity_id=row.id, action=action,
        org_unit_id=org_unit.id, before=before_out, after=after_out,
        summary=f"{'Set' if action == 'create' else 'Changed'} par for item {item_id} at {org_unit.name}",
    )
    _commit(db)
    db.refresh(row)
    return row


def delete_par(db: Session, par_level: ParLevel, user: User) -> ParLevel:
    """Soft-deactivate a par. Removing an already inactive par changes nothing."""
    if not par_level.active:
        return par_level
    before = audit_service.model_snapshot(par_level)
    par_level.active = False
    par_level.updated_by = user.name
    db.flush()
    changed_before, changed_after = audit_service.diff(before, audit_service.model_snapshot(par_level))
    audit_service.record(
        db, actor=user, entity_type=ENTITY, entity_id=par_level.id, action="deactivate",
        org_unit_id=par_level.org_unit_id, before=changed_before, after=changed_after,
        summary=f"Removed par for item {par_level.item_id}",
    )
    _commit(db)
    db.refresh(par_level)
    return par_level


def list_pars(db: Session, org_unit_id: int) -> list[tuple[ParLevel, Item]]:
    """Active pars at a site, with their items, ordered by item name."""
    _site(db, org_unit_id)
    rows = db.execute(
        select(ParLevel, Item)
        .join(Item, Item.id == ParLevel.item_id)
        .where(ParLevel.org_unit_id == org_unit_id, ParLevel.active.is_(True))
        .order_by(Item.name, ParLevel.id)
    ).all()
    return [(par, item) for par, item in rows]


# ── Shopping list ─────────────────────────────────────────────────────────────

def _preferred_links(db: Session, item_ids: list[int]) -> dict[int, tuple[SupplierItem, Supplier]]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(SupplierItem, Supplier)
        .join(Supplier, Supplier.id == SupplierItem.supplier_id)
        .where(
            SupplierItem.item_id.in_(item_ids),
            SupplierItem.is_preferred.is_(True),
            SupplierItem.is_active.is_(True),
            Supplier.is_active.is_(True),
        )
        .order_by(SupplierItem.id)
    ).all()
    preferred: dict[int, tuple[SupplierItem, Supplier]] = {}
    for link, supplier in rows:
        preferred.setdefault(link.item_id, (link, supplier))
    return preferred


def _pack_size(link: SupplierItem | None, item: Item) -> Decimal:
    if link is not None and _dec(link.pack_size) > 0:
        return _dec(link.pack_size)
    if _dec(item.pack_size) > 0:
        return _dec(item.pack_size)
    return ONE


def _round_up_to_pack(shortfall: Decimal, pack: Decimal) -> Decimal:
    multiples = (shortfall / pack).to_integral_value(rounding=ROUND_CEILING)
    return (multiples * pack).quantize(QTY)


OPEN_REQUISITION_STATUSES = (RequisitionStatus.DRAFT, RequisitionStatus.SUBMITTED, RequisitionStatus.APPROVED)
OPEN_PO_STATUSES = (POStatus.DRAFT, POStatus.SENT, POStatus.PARTIALLY_RECEIVED)


def on_order_quantities(db: Session, org_unit_id: int, item_ids: list[int]) -> dict[int, Decimal]:
    """Quantity already ordered but not yet received, per item, at this site.

    Counts open requisition lines and the outstanding part of open purchase orders.
    A converted requisition is not counted, because its purchase orders are.
    """
    totals: dict[int, Decimal] = {}
    if not item_ids:
        return totals
    requisition_rows = db.execute(
        select(RequisitionLine.item_id, RequisitionLine.quantity)
        .join(Requisition, Requisition.id == RequisitionLine.requisition_id)
        .where(
            Requisition.org_unit_id == org_unit_id,
            Requisition.status.in_(OPEN_REQUISITION_STATUSES),
            RequisitionLine.item_id.in_(item_ids),
        )
    ).all()
    po_rows = db.execute(
        select(PurchaseOrderLine.item_id, PurchaseOrderLine.quantity_ordered, PurchaseOrderLine.quantity_received)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrder.location_id == org_unit_id,
            PurchaseOrder.status.in_(OPEN_PO_STATUSES),
            PurchaseOrderLine.item_id.in_(item_ids),
        )
    ).all()
    for item_id, quantity in requisition_rows:
        totals[item_id] = totals.get(item_id, ZERO) + _dec(quantity)
    for item_id, ordered, received in po_rows:
        outstanding = max(ZERO, _dec(ordered) - _dec(received))
        totals[item_id] = totals.get(item_id, ZERO) + outstanding
    return totals


def shopping_list(db: Session, org_unit_id: int) -> ShoppingList:
    _site(db, org_unit_id)
    rows = db.execute(
        select(ParLevel, Item)
        .join(Item, Item.id == ParLevel.item_id)
        .where(ParLevel.org_unit_id == org_unit_id, ParLevel.active.is_(True), Item.is_active.is_(True))
        .order_by(Item.name, ParLevel.id)
    ).all()
    item_ids = [item.id for _, item in rows]
    preferred = _preferred_links(db, item_ids)
    on_order = on_order_quantities(db, org_unit_id, item_ids)

    groups: dict[int, SupplierGroup] = {}
    unassigned: list[ShoppingLine] = []
    for par, item in rows:
        on_hand = _dec(get_theoretical_stock(db, org_unit_id, item.id)).quantize(QTY)
        ordered = on_order.get(item.id, ZERO).quantize(QTY)
        position = on_hand + ordered
        reorder = _dec(par.reorder_point)
        if position > reorder:
            continue
        par_qty = _dec(par.par_qty)
        link_supplier = preferred.get(item.id)
        link, supplier = link_supplier if link_supplier else (None, None)
        order_qty = _round_up_to_pack(par_qty - position, _pack_size(link, item))

        price = requisition_service.current_unit_price(db, org_unit_id, item.id)
        line = ShoppingLine(
            item_id=item.id,
            item_name=item.name,
            unit=item.unit_of_measure.abbreviation if item.unit_of_measure else "",
            on_hand_qty=on_hand,
            par_qty=par_qty.quantize(QTY),
            reorder_point=reorder.quantize(QTY),
            order_qty=order_qty,
            estimated_unit_price=price,
            estimated_value=(order_qty * price).quantize(QTY) if price is not None else None,
            on_order_qty=ordered,
        )
        if supplier is None:
            unassigned.append(line)
            continue
        group = groups.setdefault(supplier.id, SupplierGroup(supplier.id, supplier.name))
        group.lines.append(line)

    return ShoppingList(
        org_unit_id=org_unit_id,
        generated_at=datetime.utcnow(),
        groups=sorted(groups.values(), key=lambda g: g.supplier_name.lower()),
        unassigned=unassigned,
    )


def create_draft_requisitions(db: Session, org_unit_id: int, user: User) -> list[Requisition]:
    """One DRAFT requisition per supplier group, all in one transaction. Never submits.

    Either every group becomes a draft and the shopping-list audit row is written, or
    nothing is written: any failure rolls the whole batch back and is re-raised. A lost
    race on a requisition number is raised as ConflictError.
    """
    _site(db, org_unit_id)
    current = shopping_list(db, org_unit_id)
    if not current.groups:
        raise ConflictError("Nothing to order: the shopping list has no orderable lines")

    try:
        requisitions = [
            requisition_service.stage_draft(
                db,
                org_unit_id=org_unit_id,
                lines=[LineSpec(item_id=l.item_id, quantity=l.order_qty) for l in group.lines],
                supplier_id=group.supplier_id,
                notes="Created from shopping list",
                requested_by=user.name,
                actor=user,
            )
            for group in current.groups
        ]
        numbers = [r.requisition_number for r in requisitions]
        audit_service.record(
            db, actor=user, entity_type=SHOPPING_ENTITY, entity_id=org_unit_id, action="create_drafts",
            org_unit_id=org_unit_id, after={"requisitions": numbers},
            summary=f"Created {len(numbers)} draft requisition(s) from shopping list: {', '.join(numbers)}",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Conflicting record was written concurrently; please retry") from exc
    except Exception:
        db.rollback()
        raise
    for r in requisitions:
        db.refresh(r)
    return requisitions
