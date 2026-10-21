"""
Requisitions and conversion to purchase orders (Feature 2).

Lifecycle of a Requisition:
  create_draft -> DRAFT (editable with update_draft)
  submit       -> prices every line (snapshot), sets total_value, then:
                    no matching approval rule -> APPROVED directly
                    matching rule             -> SUBMITTED, approval request opened
  approval decisions (approval_service.decide) -> APPROVED or REJECTED
  convert      -> APPROVED only; one PurchaseOrder per supplier, requisition CONVERTED

Unit price at submit: the catalogue price (VendorPriceCatalogue) effective today
for the requesting unit, else tenant-wide, else Item.unit_cost. No price at all
is an error. Supplier at convert: the item's preferred SupplierItem, else the
requisition's supplier_id; neither is an error.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Item, OrgUnit, Supplier, SupplierItem
from app.models.approval import ApprovalSubject
from app.models.purchase_order import POStatus, PurchaseOrder, PurchaseOrderLine
from app.models.requisition import Requisition, RequisitionLine, RequisitionStatus
from app.models.vpc import VendorPriceCatalogue
from app.services.approval_service import ConflictError, open_request

CENT = Decimal("0.01")
QTY = Decimal("0.0001")


@dataclass
class LineSpec:
    item_id: int
    quantity: object
    notes: str | None = None


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _validate_lines(db: Session, lines: list[LineSpec]) -> list[LineSpec]:
    if not lines:
        raise ValueError("A requisition needs at least one line")
    seen: set[int] = set()
    for line in lines:
        if line.item_id in seen:
            raise ValueError(f"Item {line.item_id} appears more than once")
        seen.add(line.item_id)
        if _dec(line.quantity) <= 0:
            raise ValueError(f"Quantity for item {line.item_id} must be positive")
    items = set(db.execute(select(Item.id).where(Item.id.in_(seen))).scalars())
    missing = sorted(seen - items)
    if missing:
        raise LookupError(f"Items not found: {missing}")
    return lines


def _check_supplier(db: Session, supplier_id: int | None) -> None:
    if supplier_id is not None and db.get(Supplier, supplier_id) is None:
        raise LookupError(f"Supplier {supplier_id} not found")


def _next_number(db: Session, prefix: str, number_column, day: date) -> str:
    """PREFIX-YYYYMMDD-NNNN, sequential per day. Counts from the highest existing suffix."""
    stem = f"{prefix}-{day:%Y%m%d}-"
    existing = db.execute(select(number_column).where(number_column.like(f"{stem}%"))).scalars().all()
    sequence = max((int(n.rsplit("-", 1)[1]) for n in existing), default=0) + 1
    return f"{stem}{sequence:04d}"


def _build_lines(lines: list[LineSpec]) -> list[RequisitionLine]:
    return [
        RequisitionLine(
            item_id=line.item_id,
            quantity=_dec(line.quantity).quantize(QTY),
            notes=line.notes,
        )
        for line in lines
    ]


def create_draft(
    db: Session,
    *,
    org_unit_id: int,
    lines: list[LineSpec],
    supplier_id: int | None = None,
    needed_by: date | None = None,
    notes: str | None = None,
    requested_by: str,
) -> Requisition:
    if db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    _check_supplier(db, supplier_id)
    lines = _validate_lines(db, lines)

    today = date.today()
    requisition = Requisition(
        requisition_number=_next_number(db, "REQ", Requisition.requisition_number, today),
        org_unit_id=org_unit_id,
        supplier_id=supplier_id,
        status=RequisitionStatus.DRAFT,
        needed_by=needed_by,
        notes=notes,
        requested_by=requested_by,
        lines=_build_lines(lines),
    )
    db.add(requisition)
    _commit(db)
    db.refresh(requisition)
    return requisition


def update_draft(
    db: Session,
    requisition: Requisition,
    lines: list[LineSpec],
    *,
    supplier_id: int | None,
    needed_by: date | None,
    notes: str | None,
) -> Requisition:
    """Replace a draft's header and lines. Refused once the requisition is no longer DRAFT."""
    if requisition.status != RequisitionStatus.DRAFT:
        raise ConflictError("Only draft requisitions can be edited")
    _check_supplier(db, supplier_id)
    lines = _validate_lines(db, lines)

    requisition.lines.clear()
    db.flush()  # delete old lines before inserting replacements (unique item per requisition)
    requisition.lines = _build_lines(lines)
    requisition.supplier_id = supplier_id
    requisition.needed_by = needed_by
    requisition.notes = notes
    _commit(db)
    db.refresh(requisition)
    return requisition


def _unit_price(db: Session, org_unit_id: int, item_id: int, today: date) -> Decimal:
    def catalogue_price(unit_filter) -> VendorPriceCatalogue | None:
        return db.execute(
            select(VendorPriceCatalogue).where(
                VendorPriceCatalogue.item_id == item_id,
                unit_filter,
                VendorPriceCatalogue.valid_from <= today,
                or_(VendorPriceCatalogue.valid_to.is_(None), VendorPriceCatalogue.valid_to >= today),
            ).order_by(VendorPriceCatalogue.valid_from.desc(), VendorPriceCatalogue.id.desc()).limit(1)
        ).scalar_one_or_none()

    row = catalogue_price(VendorPriceCatalogue.org_unit_id == org_unit_id)
    if row is None:
        row = catalogue_price(VendorPriceCatalogue.org_unit_id.is_(None))
    if row is not None:
        return _dec(row.price)

    item = db.get(Item, item_id)
    if item is not None and item.unit_cost is not None:
        return _dec(item.unit_cost)
    label = item.code if item is not None else str(item_id)
    raise ValueError(f"No price for item {label}: no catalogue price and no unit cost")


def submit(db: Session, requisition: Requisition, today: date | None = None) -> Requisition:
    if requisition.status != RequisitionStatus.DRAFT:
        raise ConflictError("Only draft requisitions can be submitted")
    if not requisition.lines:
        raise ValueError("A requisition needs at least one line")
    today = today or date.today()

    # Price everything first so a missing price leaves the draft untouched.
    prices = {line.item_id: _unit_price(db, requisition.org_unit_id, line.item_id, today)
              for line in requisition.lines}
    total = Decimal(0)
    for line in requisition.lines:
        line.unit_price = prices[line.item_id]
        total += _dec(line.quantity) * prices[line.item_id]

    requisition.total_value = total.quantize(CENT)
    requisition.submitted_at = datetime.utcnow()
    requisition.status = RequisitionStatus.SUBMITTED
    db.flush()

    approval = open_request(
        db, ApprovalSubject.REQUISITION, requisition.id,
        requisition.org_unit_id, requisition.total_value,
    )
    if approval is None:
        requisition.status = RequisitionStatus.APPROVED  # no rule matched: no approval needed
    _commit(db)
    db.refresh(requisition)
    return requisition


def _preferred_supplier_item(db: Session, item_id: int) -> SupplierItem | None:
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


def _supplier_item_for(db: Session, supplier_id: int, item_id: int) -> SupplierItem | None:
    return db.execute(
        select(SupplierItem).where(
            SupplierItem.supplier_id == supplier_id,
            SupplierItem.item_id == item_id,
            SupplierItem.is_active.is_(True),
        ).order_by(SupplierItem.id).limit(1)
    ).scalar_one_or_none()


def _line_supplier(db: Session, requisition: Requisition, line: RequisitionLine) -> tuple[int, int | None]:
    preferred = _preferred_supplier_item(db, line.item_id)
    if preferred is not None:
        return preferred.supplier_id, preferred.id
    if requisition.supplier_id is not None:
        link = _supplier_item_for(db, requisition.supplier_id, line.item_id)
        return requisition.supplier_id, link.id if link is not None else None
    code = line.item.code if line.item is not None else str(line.item_id)
    raise ValueError(
        f"No supplier for item {code}: set a preferred supplier for it or a supplier on the requisition"
    )


def convert(db: Session, requisition: Requisition, today: date | None = None) -> list[PurchaseOrder]:
    """Split an APPROVED requisition into one DRAFT purchase order per supplier."""
    if requisition.status != RequisitionStatus.APPROVED:
        raise ConflictError("Only approved requisitions can be converted")
    today = today or date.today()

    # Resolve every line's supplier before creating anything.
    groups: dict[int, list[tuple[RequisitionLine, int | None]]] = {}
    for line in requisition.lines:
        supplier_id, supplier_item_id = _line_supplier(db, requisition, line)
        groups.setdefault(supplier_id, []).append((line, supplier_item_id))

    purchase_orders: list[PurchaseOrder] = []
    for supplier_id, group in groups.items():
        purchase_order = PurchaseOrder(
            po_number=_next_number(db, "PO", PurchaseOrder.po_number, today),
            supplier_id=supplier_id,
            location_id=requisition.org_unit_id,
            status=POStatus.DRAFT,
            order_date=today,
            notes=f"From requisition {requisition.requisition_number}",
            created_by=requisition.requested_by,
        )
        db.add(purchase_order)
        db.flush()

        value = Decimal(0)
        for line, supplier_item_id in group:
            unit_price = _dec(line.unit_price)  # snapshot taken at submit
            quantity = _dec(line.quantity)
            db.add(PurchaseOrderLine(
                purchase_order_id=purchase_order.id,
                item_id=line.item_id,
                supplier_item_id=supplier_item_id,
                quantity_ordered=quantity,
                unit_price=unit_price,
                quantity_received=0,
            ))
            value += quantity * unit_price
        db.flush()

        open_request(
            db, ApprovalSubject.PURCHASE_ORDER, purchase_order.id,
            requisition.org_unit_id, value.quantize(CENT),
        )
        purchase_orders.append(purchase_order)

    requisition.status = RequisitionStatus.CONVERTED
    _commit(db)
    for purchase_order in purchase_orders:
        db.refresh(purchase_order)
    return purchase_orders


def _commit(db: Session) -> None:
    """Commit, turning a lost race on a generated number into a retryable conflict."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Conflicting record was created concurrently; please retry") from exc
