from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.item import Department
from app.models.spot_check import SpotCheckSession, SpotCheckItem, SpotCheckStatus
from app.services.spot_check_selector import select_items_for_session, get_theoretical_stock

router = APIRouter(prefix="/spot-checks", tags=["spot-checks"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class GenerateSessionRequest(BaseModel):
    location_id: int
    department: Department
    session_slot: int = 1  # 1 = morning, 2 = afternoon
    assigned_to: str | None = None
    n_items: int = 5


class SpotCheckItemOut(BaseModel):
    id: int
    item_id: int
    item_code: str
    item_name: str
    item_category: str
    department: Department
    unit_abbreviation: str
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
    items: list[SpotCheckItemOut]

    class Config:
        from_attributes = True


class CountSubmission(BaseModel):
    actual_quantity: float
    counted_by: str
    notes: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enrich_item_out(si: SpotCheckItem) -> SpotCheckItemOut:
    return SpotCheckItemOut(
        id=si.id,
        item_id=si.item_id,
        item_code=si.item.code,
        item_name=si.item.name,
        item_category=si.item.category,
        department=si.item.department,
        unit_abbreviation=si.item.unit_of_measure.abbreviation,
        theoretical_quantity=si.theoretical_quantity,
        actual_quantity=si.actual_quantity,
        counted_by=si.counted_by,
        counted_at=si.counted_at,
        variance_quantity=si.variance_quantity,
        variance_value=si.variance_value,
        variance_pct=si.variance_pct,
        selection_score=float(si.selection_score) if si.selection_score else None,
        days_since_last_check=si.days_since_last_check,
        notes=si.notes,
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
        items=[_enrich_item_out(i) for i in session.items],
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=SessionOut, status_code=201)
def generate_session(payload: GenerateSessionRequest, db: Session = Depends(get_db)):
    """
    Generate a new spot-check session for a department.
    Runs the selection algorithm and returns the chosen items with theoretical quantities.
    For afternoon sessions, pass the morning session id to exclude those items.
    """
    # Avoid duplicating today's session for this slot
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

    # For slot 2, exclude items already in slot 1 today
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
        n=payload.n_items,
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
        db.add(SpotCheckItem(
            session_id=session.id,
            item_id=s.item.id,
            selection_score=s.total_score,
            sales_velocity_score=s.velocity_score,
            variance_history_score=s.variance_score,
            days_since_last_check=s.days_since_last_check,
            theoretical_quantity=theoretical,
        ))

    db.commit()
    db.refresh(session)
    return _session_to_out(session)


@router.get("/today", response_model=list[SessionOut])
def get_today_sessions(location_id: int, db: Session = Depends(get_db)):
    """Returns all spot-check sessions for today at a given location."""
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


@router.post("/{session_id}/items/{item_id}/count", response_model=SpotCheckItemOut)
def submit_count(
    session_id: int,
    item_id: int,
    payload: CountSubmission,
    db: Session = Depends(get_db),
):
    """Manager submits their physical count for one item."""
    session = db.get(SpotCheckSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == SpotCheckStatus.COMPLETE:
        raise HTTPException(400, "Session already completed")

    spot_item = (
        db.query(SpotCheckItem)
        .filter(SpotCheckItem.session_id == session_id, SpotCheckItem.item_id == item_id)
        .first()
    )
    if not spot_item:
        raise HTTPException(404, "Item not in this session")

    spot_item.actual_quantity = payload.actual_quantity
    spot_item.counted_by = payload.counted_by
    spot_item.counted_at = datetime.utcnow()
    spot_item.notes = payload.notes

    if spot_item.theoretical_quantity is not None:
        spot_item.variance_quantity = payload.actual_quantity - spot_item.theoretical_quantity
        unit_cost = float(spot_item.unit_cost or 0)
        spot_item.variance_value = spot_item.variance_quantity * unit_cost
        if spot_item.theoretical_quantity > 0:
            spot_item.variance_pct = (spot_item.variance_quantity / spot_item.theoretical_quantity) * 100
        else:
            spot_item.variance_pct = None

    # Update session status
    all_items = session.items
    counted = sum(1 for i in all_items if i.actual_quantity is not None)
    if counted == len(all_items):
        session.status = SpotCheckStatus.COMPLETE
        session.completed_at = datetime.utcnow()
    else:
        session.status = SpotCheckStatus.PARTIAL

    db.commit()
    db.refresh(spot_item)
    return _enrich_item_out(spot_item)


@router.get("/history/{location_id}", response_model=list[SessionOut])
def get_history(
    location_id: int,
    department: Department | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    q = (
        db.query(SpotCheckSession)
        .filter(SpotCheckSession.location_id == location_id)
    )
    if department:
        q = q.filter(SpotCheckSession.department == department)
    sessions = q.order_by(SpotCheckSession.session_date.desc()).limit(limit).all()
    return [_session_to_out(s) for s in sessions]
