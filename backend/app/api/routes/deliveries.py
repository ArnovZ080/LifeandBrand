from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date, datetime
from app.db.database import get_db
from app.models.delivery import Delivery, DeliveryLine, DeliveryStatus
from app.models.stock import StockMovement, MovementType

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


class DeliveryLineCreate(BaseModel):
    item_id: int
    po_line_id: int | None = None
    quantity_delivered: float
    quantity_accepted: float | None = None
    unit_price: float | None = None
    has_discrepancy: bool = False
    discrepancy_notes: str | None = None


class DeliveryCreate(BaseModel):
    purchase_order_id: int | None = None
    supplier_id: int
    location_id: int
    delivery_date: date
    supplier_delivery_note: str | None = None
    received_by: str | None = None
    notes: str | None = None
    lines: list[DeliveryLineCreate]


class DeliveryOut(BaseModel):
    id: int
    grn_number: str
    supplier_id: int
    location_id: int
    delivery_date: date
    status: DeliveryStatus
    received_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True


def _next_grn(db: Session) -> str:
    count = db.query(Delivery).count()
    return f"GRN-{count + 1:05d}"


@router.get("/", response_model=list[DeliveryOut])
def list_deliveries(location_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Delivery)
    if location_id:
        q = q.filter(Delivery.location_id == location_id)
    return q.order_by(Delivery.delivery_date.desc()).all()


@router.post("/", response_model=DeliveryOut, status_code=201)
def create_delivery(payload: DeliveryCreate, db: Session = Depends(get_db)):
    lines_data = payload.lines
    delivery = Delivery(
        grn_number=_next_grn(db),
        purchase_order_id=payload.purchase_order_id,
        supplier_id=payload.supplier_id,
        location_id=payload.location_id,
        delivery_date=payload.delivery_date,
        supplier_delivery_note=payload.supplier_delivery_note,
        received_by=payload.received_by,
        notes=payload.notes,
    )
    db.add(delivery)
    db.flush()
    for line in lines_data:
        db.add(DeliveryLine(delivery_id=delivery.id, **line.model_dump()))
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/{delivery_id}/accept")
def accept_delivery(delivery_id: int, accepted_by: str, db: Session = Depends(get_db)):
    """
    Marks a delivery as accepted and posts stock movements to the ledger.
    This is the action that actually increases stock.
    """
    delivery = db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "Delivery not found")
    if delivery.status == DeliveryStatus.ACCEPTED:
        raise HTTPException(400, "Delivery already accepted")

    for line in delivery.lines:
        qty = line.quantity_accepted if line.quantity_accepted is not None else line.quantity_delivered
        db.add(StockMovement(
            location_id=delivery.location_id,
            item_id=line.item_id,
            movement_type=MovementType.DELIVERY,
            quantity=qty,
            unit_cost=line.unit_price,
            reference_id=delivery.id,
            reference_type="delivery",
            created_by=accepted_by,
        ))

    delivery.status = DeliveryStatus.ACCEPTED
    db.commit()
    return {"message": "Delivery accepted and stock updated", "grn_number": delivery.grn_number}
