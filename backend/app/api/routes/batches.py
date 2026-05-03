"""
Batch monitoring — expiry alerts and FIFO status for perishable items.
This is what the kitchen manager checks at the start of each shift.
"""

from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.database import get_db
from app.models.batch import ItemBatch, BatchStatus

router = APIRouter(prefix="/batches", tags=["batches"])


class BatchOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    item_code: str
    location_id: int
    batch_reference: str | None
    received_date: date
    best_before_date: date | None
    shelf_life_days: int | None
    days_until_expiry: int | None
    quantity_received: float
    quantity_remaining: float
    unit_cost: float | None
    status: BatchStatus

    class Config:
        from_attributes = True


def _to_out(batch: ItemBatch) -> BatchOut:
    days_until = (
        (batch.best_before_date - date.today()).days
        if batch.best_before_date else None
    )
    return BatchOut(
        id=batch.id,
        item_id=batch.item_id,
        item_name=batch.item.name,
        item_code=batch.item.code,
        location_id=batch.location_id,
        batch_reference=batch.batch_reference,
        received_date=batch.received_date,
        best_before_date=batch.best_before_date,
        shelf_life_days=batch.shelf_life_days,
        days_until_expiry=days_until,
        quantity_received=float(batch.quantity_received),
        quantity_remaining=float(batch.quantity_remaining),
        unit_cost=float(batch.unit_cost) if batch.unit_cost else None,
        status=batch.status,
    )


@router.get("/expiring", response_model=list[BatchOut])
def get_expiring_batches(
    location_id: int,
    within_days: int = 2,
    db: Session = Depends(get_db),
):
    """
    Returns all active batches expiring within `within_days` days (default 2).
    This is the daily freshness alert list — check at shift start.
    """
    from datetime import timedelta
    cutoff = date.today() + timedelta(days=within_days)
    batches = (
        db.query(ItemBatch)
        .filter(
            ItemBatch.location_id == location_id,
            ItemBatch.best_before_date.isnot(None),
            ItemBatch.best_before_date <= cutoff,
            ItemBatch.status.in_([BatchStatus.ACTIVE, BatchStatus.EXPIRING_SOON]),
        )
        .order_by(ItemBatch.best_before_date.asc())
        .all()
    )
    # Refresh statuses in case they haven't been updated by a background job
    for b in batches:
        b.refresh_status()
    db.commit()
    return [_to_out(b) for b in batches]


@router.get("/active", response_model=list[BatchOut])
def get_active_batches(
    location_id: int,
    item_id: int | None = None,
    db: Session = Depends(get_db),
):
    """All active batches at a location, optionally filtered by item."""
    q = db.query(ItemBatch).filter(
        ItemBatch.location_id == location_id,
        ItemBatch.status.in_([BatchStatus.ACTIVE, BatchStatus.EXPIRING_SOON]),
    )
    if item_id:
        q = q.filter(ItemBatch.item_id == item_id)
    batches = q.order_by(ItemBatch.best_before_date.asc().nulls_last()).all()
    for b in batches:
        b.refresh_status()
    db.commit()
    return [_to_out(b) for b in batches]
