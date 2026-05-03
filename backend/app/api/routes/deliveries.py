from datetime import datetime, date as date_type
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.database import get_db
from app.models.delivery import Delivery, DeliveryLine, DeliveryStatus
from app.models.stock import StockMovement, MovementType
from app.models.batch import ItemBatch, BatchStatus
from app.models.item import Item

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


class DeliveryLineCreate(BaseModel):
    item_id: int
    po_line_id: int | None = None
    quantity_delivered: float
    quantity_accepted: float | None = None
    unit_price: float | None = None
    has_discrepancy: bool = False
    discrepancy_notes: str | None = None
    # Perishable fields — required if the item is perishable
    best_before_date: date_type | None = None
    batch_reference: str | None = None


class DeliveryCreate(BaseModel):
    purchase_order_id: int | None = None
    supplier_id: int
    location_id: int
    delivery_date: date_type
    supplier_delivery_note: str | None = None
    received_by: str | None = None
    notes: str | None = None
    lines: list[DeliveryLineCreate]


class DeliveryLineOut(BaseModel):
    id: int
    item_id: int
    quantity_delivered: float
    quantity_accepted: float | None
    unit_price: float | None
    has_discrepancy: bool
    best_before_date: date_type | None
    batch_reference: str | None

    class Config:
        from_attributes = True


class DeliveryOut(BaseModel):
    id: int
    grn_number: str
    supplier_id: int
    location_id: int
    delivery_date: date_type
    status: DeliveryStatus
    received_by: str | None
    created_at: datetime
    lines: list[DeliveryLineOut]

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
    for line in payload.lines:
        db.add(DeliveryLine(delivery_id=delivery.id, **line.model_dump()))
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/{delivery_id}/accept", response_model=DeliveryOut)
def accept_delivery(delivery_id: int, accepted_by: str, db: Session = Depends(get_db)):
    """
    Accept a delivery:
    1. Posts stock movements to the ledger (increases theoretical stock).
    2. For perishable items, creates an ItemBatch so stock is tracked by
       received date and best-before date.
    """
    delivery = db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "Delivery not found")
    if delivery.status == DeliveryStatus.ACCEPTED:
        raise HTTPException(400, "Delivery already accepted")

    for line in delivery.lines:
        qty = float(line.quantity_accepted if line.quantity_accepted is not None else line.quantity_delivered)
        unit_cost = float(line.unit_price or 0)

        # Stock movement — updates theoretical stock for variance calculation
        db.add(StockMovement(
            location_id=delivery.location_id,
            item_id=line.item_id,
            movement_type=MovementType.DELIVERY,
            quantity=qty,
            unit_cost=unit_cost,
            reference_id=delivery.id,
            reference_type="delivery",
            created_by=accepted_by,
        ))

        # Batch creation for perishable items
        item = db.get(Item, line.item_id)
        if item and item.is_perishable:
            # Calculate best_before from shelf life if not explicitly provided
            best_before = line.best_before_date
            shelf_life_days = None
            if best_before is None and item.default_shelf_life_days:
                from datetime import timedelta
                best_before = delivery.delivery_date + timedelta(days=item.default_shelf_life_days)
                shelf_life_days = item.default_shelf_life_days
            elif best_before is not None:
                shelf_life_days = (best_before - delivery.delivery_date).days

            batch = ItemBatch(
                item_id=line.item_id,
                location_id=delivery.location_id,
                delivery_line_id=line.id,
                batch_reference=line.batch_reference or f"{delivery.grn_number}-L{line.id}",
                received_date=delivery.delivery_date,
                best_before_date=best_before,
                shelf_life_days=shelf_life_days,
                quantity_received=qty,
                quantity_remaining=qty,
                unit_cost=unit_cost or None,
            )
            batch.refresh_status()
            db.add(batch)

    delivery.status = DeliveryStatus.ACCEPTED
    db.commit()
    db.refresh(delivery)
    return delivery
