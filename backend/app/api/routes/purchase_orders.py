from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date, datetime
from app.db.database import get_db
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine, POStatus
from app.services import audit_service

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


class POLineCreate(BaseModel):
    item_id: int
    supplier_item_id: int | None = None
    quantity_ordered: float
    unit_price: float


class POCreate(BaseModel):
    supplier_id: int
    location_id: int
    order_date: date
    expected_delivery_date: date | None = None
    notes: str | None = None
    created_by: str | None = None
    lines: list[POLineCreate]


class POLineOut(BaseModel):
    id: int
    item_id: int
    quantity_ordered: float
    unit_price: float
    quantity_received: float

    class Config:
        from_attributes = True


class POOut(BaseModel):
    id: int
    po_number: str
    supplier_id: int
    location_id: int
    status: POStatus
    order_date: date
    expected_delivery_date: date | None
    notes: str | None
    created_by: str | None
    created_at: datetime
    lines: list[POLineOut]

    class Config:
        from_attributes = True


def _next_po_number(db: Session) -> str:
    count = db.query(PurchaseOrder).count()
    return f"PO-{count + 1:05d}"


@router.get("/", response_model=list[POOut])
def list_pos(
    location_id: int | None = None,
    status: POStatus | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(PurchaseOrder)
    if location_id:
        q = q.filter(PurchaseOrder.location_id == location_id)
    if status:
        q = q.filter(PurchaseOrder.status == status)
    return q.order_by(PurchaseOrder.order_date.desc()).all()


@router.post("/", response_model=POOut, status_code=201)
def create_po(payload: POCreate, db: Session = Depends(get_db)):
    lines_data = payload.lines
    po = PurchaseOrder(
        po_number=_next_po_number(db),
        supplier_id=payload.supplier_id,
        location_id=payload.location_id,
        order_date=payload.order_date,
        expected_delivery_date=payload.expected_delivery_date,
        notes=payload.notes,
        created_by=payload.created_by,
    )
    db.add(po)
    db.flush()
    for line in lines_data:
        db.add(PurchaseOrderLine(purchase_order_id=po.id, **line.model_dump()))
    db.flush()
    after = audit_service.model_snapshot(po)
    after["lines"] = [audit_service.model_snapshot(line) for line in po.lines]
    audit_service.record(
        db, actor=None, actor_name=payload.created_by, entity_type="purchase_order",
        entity_id=po.id, action="create", org_unit_id=po.location_id, after=after,
        summary=f"Created {po.po_number} with {len(lines_data)} line(s)",
    )
    db.commit()
    db.refresh(po)
    return po


@router.get("/{po_id}", response_model=POOut)
def get_po(po_id: int, db: Session = Depends(get_db)):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    return po


@router.patch("/{po_id}/status")
def update_po_status(po_id: int, status: POStatus, db: Session = Depends(get_db)):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    before = audit_service.model_snapshot(po)
    po.status = status
    db.flush()
    changed_before, changed_after = audit_service.diff(before, audit_service.model_snapshot(po))
    audit_service.record(
        db, actor=None, entity_type="purchase_order", entity_id=po.id, action="update",
        org_unit_id=po.location_id, before=changed_before, after=changed_after,
        summary=f"{po.po_number} status set to {status.value}",
    )
    db.commit()
    return {"id": po_id, "status": status}
