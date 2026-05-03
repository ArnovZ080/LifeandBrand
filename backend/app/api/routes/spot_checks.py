from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.item import Department
from app.models.spot_check import SpotCheckSession, SpotCheckItem, SpotCheckBatchCount, SpotCheckStatus
from app.services.spot_check_selector import (
    select_items_for_session,
    get_theoretical_stock,
    get_active_batches,
    BASE_ITEMS_PER_SESSION,
    CYCLE_DAYS,
)

router = APIRouter(prefix="/spot-checks", tags=["spot-checks"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class GenerateSessionRequest(BaseModel):
    location_id: int
    department: Department
    session_slot: int = 1
    assigned_to: str | None = None
    base_n: int = BASE_ITEMS_PER_SESSION


class BatchCountOut(BaseModel):
    id: int
    batch_id: int
    batch_reference: str | None
    received_date: date | None
    best_before_date: date | None
    days_until_expiry: int | None
    expected_quantity: float | None
    actual_quantity: float | None
    counted_by: str | None
    counted_at: datetime | None
    variance_quantity: float | None
    notes: str | None

    class Config:
        from_attributes = True


class SpotCheckItemOut(BaseModel):
    id: int
    item_id: int
    item_code: str
    item_name: str
    item_category: str
    department: Department
    unit_abbreviation: str
    unit_cost: float | None
    is_perishable: bool
    is_overdue: bool
    theoretical_quantity: float | None
    actual_quantity: float | None
    counted_by: str | None
    counted_at: datetime | None
    variance_quantity: float | None
    variance_value: float | None
    variance_pct: float | None
    selection_score: float | None
    days_since_last_check: int | None
    notes: str | None
    batch_counts: list[BatchCountOut]

    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: int
    location_id: int
    department: Department
    session_date: date
    session_slot: int
    status: SpotCheckStatus
    assigned_to: str | None
    notified_at: datetime | None
    completed_at: datetime | None
    overdue_count: int
    items: list[SpotCheckItemOut]

    class Config:
        from_attributes = True


class CountSubmission(BaseModel):
    actual_quantity: float
    counted_by: str
    notes: str | None = None


class BatchCountSubmission(BaseModel):
    batch_id: int
    actual_quantity: float
    counted_by: str
    notes: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _batch_count_to_out(bc: SpotCheckBatchCount) -> BatchCountOut:
    days_until = (
        (bc.best_before_date - date.today()).days
        if bc.best_before_date else None
    )
    return BatchCountOut(
        id=bc.id,
        batch_id=bc.batch_id,
        batch_reference=bc.batch_reference,
        received_date=bc.received_date,
        best_before_date=bc.best_before_date,
        days_until_expiry=days_until,
        expected_quantity=float(bc.expected_quantity) if bc.expected_quantity is not None else None,
        actual_quantity=float(bc.actual_quantity) if bc.actual_quantity is not None else None,
        counted_by=bc.counted_by,
        counted_at=bc.counted_at,
        variance_quantity=float(bc.variance_quantity) if bc.variance_quantity is not None else None,
        notes=bc.notes,
    )


def _item_to_out(si: SpotCheckItem) -> SpotCheckItemOut:
    return SpotCheckItemOut(
        id=si.id,
        item_id=si.item_id,
        item_code=si.item.code,
        item_name=si.item.name,
        item_category=si.item.category,
        department=si.item.department,
        unit_abbreviation=si.item.unit_of_measure.abbreviation,
        unit_cost=float(si.unit_cost) if si.unit_cost else None,
        is_perishable=si.is_perishable,
        is_overdue=si.is_overdue,
        theoretical_quantity=float(si.theoretical_quantity) if si.theoretical_quantity is not None else None,
        actual_quantity=float(si.actual_quantity) if si.actual_quantity is not None else None,
        counted_by=si.counted_by,
        counted_at=si.counted_at,
        variance_quantity=float(si.variance_quantity) if si.variance_quantity is not None else None,
        variance_value=float(si.variance_value) if si.variance_value is not None else None,
        variance_pct=float(si.variance_pct) if si.variance_pct is not None else None,
        selection_score=float(si.selection_score) if si.selection_score else None,
        days_since_last_check=si.days_since_last_check,
        notes=si.notes,
        batch_counts=[_batch_count_to_out(bc) for bc in si.batch_counts],
    )


def _session_to_out(session: SpotCheckSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        location_id=session.location_id,
        department=session.department,
        session_date=session.session_date,
        session_slot=session.session_slot,
        status=session.status,
        assigned_to=session.assigned_to,
        notified_at=session.notified_at,
        completed_at=session.completed_at,
        overdue_count=sum(1 for i in session.items if i.is_overdue),
        items=[_item_to_out(i) for i in session.items],
    )


def _update_session_status(session: SpotCheckSession) -> None:
    """Recalculate session status based on count completion across all items."""
    all_items = session.items
    if not all_items:
        return
    completed = sum(1 for i in all_items if _item_is_counted(i))
    if completed == len(all_items):
        session.status = SpotCheckStatus.COMPLETE
        session.completed_at = datetime.utcnow()
    elif completed > 0:
        session.status = SpotCheckStatus.PARTIAL


def _item_is_counted(si: SpotCheckItem) -> bool:
    if si.is_perishable:
        return bool(si.batch_counts) and all(bc.actual_quantity is not None for bc in si.batch_counts)
    return si.actual_quantity is not None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=SessionOut, status_code=201)
def generate_session(payload: GenerateSessionRequest, db: Session = Depends(get_db)):
    existing = (
        db.query(SpotCheckSession)
        .filter(
            SpotCheckSession.location_id == payload.location_id,
            SpotCheckSession.department == payload.department,
            SpotCheckSession.session_date == date.today(),
            SpotCheckSession.session_slot == payload.session_slot,
        )
        .first()
    )
    if existing:
        raise HTTPException(400, f"Session already exists for {payload.department} slot {payload.session_slot} today")

    exclude_ids: list[int] = []
    if payload.session_slot == 2:
        morning = (
            db.query(SpotCheckSession)
            .filter(
                SpotCheckSession.location_id == payload.location_id,
                SpotCheckSession.department == payload.department,
                SpotCheckSession.session_date == date.today(),
                SpotCheckSession.session_slot == 1,
            )
            .first()
        )
        if morning:
            exclude_ids = [i.item_id for i in morning.items]

    scored = select_items_for_session(
        db,
        location_id=payload.location_id,
        department=payload.department,
        base_n=payload.base_n,
        exclude_item_ids=exclude_ids,
    )

    if not scored:
        raise HTTPException(422, f"No active items found for department '{payload.department}'")

    session = SpotCheckSession(
        location_id=payload.location_id,
        department=payload.department,
        session_date=date.today(),
        session_slot=payload.session_slot,
        assigned_to=payload.assigned_to,
    )
    db.add(session)
    db.flush()

    for s in scored:
        theoretical = get_theoretical_stock(db, payload.location_id, s.item.id)
        si = SpotCheckItem(
            session_id=session.id,
            item_id=s.item.id,
            selection_score=s.total_score,
            velocity_score=s.velocity_score,
            value_score=s.value_score,
            variance_history_score=s.variance_score,
            days_since_last_check=s.days_since_last_check,
            is_overdue=s.is_overdue,
            is_perishable=s.item.is_perishable,
            theoretical_quantity=theoretical,
            unit_cost=float(s.item.unit_cost) if s.item.unit_cost else None,
        )
        db.add(si)
        db.flush()

        # For perishable items, pre-populate batch count rows from active batches
        if s.item.is_perishable:
            batches = get_active_batches(db, payload.location_id, s.item.id)
            for batch in batches:
                db.add(SpotCheckBatchCount(
                    spot_check_item_id=si.id,
                    batch_id=batch.id,
                    received_date=batch.received_date,
                    best_before_date=batch.best_before_date,
                    batch_reference=batch.batch_reference,
                    expected_quantity=float(batch.quantity_remaining),
                ))

    db.commit()
    db.refresh(session)
    return _session_to_out(session)


@router.get("/today", response_model=list[SessionOut])
def get_today_sessions(location_id: int, db: Session = Depends(get_db)):
    sessions = (
        db.query(SpotCheckSession)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.session_date == date.today(),
        )
        .order_by(SpotCheckSession.department, SpotCheckSession.session_slot)
        .all()
    )
    return [_session_to_out(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(SpotCheckSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return _session_to_out(session)


@router.post("/{session_id}/items/{spot_item_id}/count", response_model=SpotCheckItemOut)
def submit_count(
    session_id: int,
    spot_item_id: int,
    payload: CountSubmission,
    db: Session = Depends(get_db),
):
    """Submit a count for a non-perishable item."""
    session = db.get(SpotCheckSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    si = db.get(SpotCheckItem, spot_item_id)
    if not si or si.session_id != session_id:
        raise HTTPException(404, "Item not in this session")
    if si.is_perishable:
        raise HTTPException(400, "Use the batch count endpoint for perishable items")

    si.actual_quantity = payload.actual_quantity
    si.counted_by = payload.counted_by
    si.counted_at = datetime.utcnow()
    si.notes = payload.notes

    if si.theoretical_quantity is not None:
        si.variance_quantity = payload.actual_quantity - float(si.theoretical_quantity)
        unit_cost = float(si.unit_cost or 0)
        si.variance_value = si.variance_quantity * unit_cost
        if float(si.theoretical_quantity) > 0:
            si.variance_pct = (si.variance_quantity / float(si.theoretical_quantity)) * 100

    _update_session_status(session)
    db.commit()
    db.refresh(si)
    return _item_to_out(si)


@router.post("/{session_id}/items/{spot_item_id}/batch-count", response_model=SpotCheckItemOut)
def submit_batch_count(
    session_id: int,
    spot_item_id: int,
    payload: BatchCountSubmission,
    db: Session = Depends(get_db),
):
    """
    Submit a count for one batch of a perishable item.
    Call once per batch. When all batches are counted the item is marked complete.
    """
    session = db.get(SpotCheckSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    si = db.get(SpotCheckItem, spot_item_id)
    if not si or si.session_id != session_id:
        raise HTTPException(404, "Item not in this session")
    if not si.is_perishable:
        raise HTTPException(400, "Use the standard count endpoint for non-perishable items")

    batch_count = next((bc for bc in si.batch_counts if bc.batch_id == payload.batch_id), None)
    if not batch_count:
        raise HTTPException(404, f"Batch {payload.batch_id} not in this session item")

    batch_count.actual_quantity = payload.actual_quantity
    batch_count.counted_by = payload.counted_by
    batch_count.counted_at = datetime.utcnow()
    batch_count.notes = payload.notes

    if batch_count.expected_quantity is not None:
        batch_count.variance_quantity = payload.actual_quantity - float(batch_count.expected_quantity)

    if batch_count.best_before_date:
        batch_count.days_until_expiry = (batch_count.best_before_date - date.today()).days

    # Roll up totals to the parent item once all batches have been counted
    if all(bc.actual_quantity is not None for bc in si.batch_counts):
        total_actual = sum(float(bc.actual_quantity) for bc in si.batch_counts)
        total_expected = sum(float(bc.expected_quantity or 0) for bc in si.batch_counts)
        si.actual_quantity = total_actual
        si.theoretical_quantity = total_expected
        si.variance_quantity = total_actual - total_expected
        si.counted_by = payload.counted_by
        si.counted_at = datetime.utcnow()
        unit_cost = float(si.unit_cost or 0)
        si.variance_value = si.variance_quantity * unit_cost
        if total_expected > 0:
            si.variance_pct = (si.variance_quantity / total_expected) * 100

    _update_session_status(session)
    db.commit()
    db.refresh(si)
    return _item_to_out(si)


@router.get("/history/{location_id}", response_model=list[SessionOut])
def get_history(
    location_id: int,
    department: Department | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    q = db.query(SpotCheckSession).filter(SpotCheckSession.location_id == location_id)
    if department:
        q = q.filter(SpotCheckSession.department == department)
    sessions = q.order_by(SpotCheckSession.session_date.desc()).limit(limit).all()
    return [_session_to_out(s) for s in sessions]


@router.get("/coverage/{location_id}/{department}")
def get_cycle_coverage(location_id: int, department: Department, db: Session = Depends(get_db)):
    """
    Shows how many items in this department have and haven't been checked
    within the current {CYCLE_DAYS}-day window. Useful for monitoring cycle health.
    """
    from datetime import timedelta
    from app.models.item import Item

    since = date.today() - timedelta(days=CYCLE_DAYS)
    all_items = (
        db.query(Item)
        .filter(Item.department == department, Item.is_active == True)
        .all()
    )
    recently_checked_ids = set(
        row.item_id for row in
        db.query(SpotCheckItem.item_id)
        .join(SpotCheckSession)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.department == department,
            SpotCheckSession.session_date >= since,
            SpotCheckItem.counted_at.isnot(None),
        )
        .all()
    )
    covered = [i for i in all_items if i.id in recently_checked_ids]
    overdue = [i for i in all_items if i.id not in recently_checked_ids]

    return {
        "cycle_days": CYCLE_DAYS,
        "total_items": len(all_items),
        "covered_in_cycle": len(covered),
        "overdue": len(overdue),
        "coverage_pct": round(len(covered) / len(all_items) * 100, 1) if all_items else 0,
        "overdue_items": [{"id": i.id, "code": i.code, "name": i.name} for i in overdue],
    }
