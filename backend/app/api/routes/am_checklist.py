from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.am_checklist import AMChecklistTask, AMChecklistEntry, ChecklistFrequency

router = APIRouter(prefix="/am/checklist", tags=["area-manager"])


def _period_date(frequency: ChecklistFrequency, ref: date | None = None) -> date:
    """Canonical period-start date for a given frequency."""
    d = ref or date.today()
    if frequency == ChecklistFrequency.DAILY:
        return d
    if frequency == ChecklistFrequency.WEEKLY:
        return d - timedelta(days=d.weekday())  # Monday of current week
    if frequency == ChecklistFrequency.MONTHLY:
        return d.replace(day=1)
    return d  # adhoc uses today


# ── Schemas ────────────────────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: int
    frequency: ChecklistFrequency
    order_num: int
    title: str

    class Config:
        from_attributes = True


class EntryOut(BaseModel):
    id: int
    task_id: int
    period_date: date
    completed: bool
    completed_by: str | None
    completed_at: datetime | None
    notes: str | None
    validated: bool
    validated_by: str | None
    validated_at: datetime | None

    class Config:
        from_attributes = True


class TaskWithEntry(BaseModel):
    task: TaskOut
    entry: EntryOut | None


class CompleteRequest(BaseModel):
    location_id: int
    completed_by: str
    notes: str | None = None


class ValidateRequest(BaseModel):
    validated_by: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=dict[str, list[TaskOut]])
def get_tasks(db: Session = Depends(get_db)):
    """Return all active tasks grouped by frequency."""
    tasks = db.query(AMChecklistTask).filter(AMChecklistTask.is_active == True).order_by(
        AMChecklistTask.frequency, AMChecklistTask.order_num
    ).all()
    grouped: dict[str, list] = {f.value: [] for f in ChecklistFrequency}
    for t in tasks:
        grouped[t.frequency.value].append(TaskOut.model_validate(t))
    return grouped


@router.get("/period", response_model=list[TaskWithEntry])
def get_period_checklist(
    location_id: int,
    frequency: ChecklistFrequency,
    ref_date: date | None = None,
    db: Session = Depends(get_db),
):
    """
    Returns all tasks for a frequency with their completion entry for the
    current period (or the period containing ref_date).
    """
    period = _period_date(frequency, ref_date)
    tasks = (
        db.query(AMChecklistTask)
        .filter(AMChecklistTask.frequency == frequency, AMChecklistTask.is_active == True)
        .order_by(AMChecklistTask.order_num)
        .all()
    )
    entries = {
        e.task_id: e
        for e in db.query(AMChecklistEntry).filter(
            AMChecklistEntry.location_id == location_id,
            AMChecklistEntry.period_date == period,
        ).all()
    }
    return [TaskWithEntry(task=TaskOut.model_validate(t), entry=entries.get(t.id)) for t in tasks]


@router.post("/tasks/{task_id}/complete", response_model=EntryOut)
def mark_complete(task_id: int, payload: CompleteRequest, db: Session = Depends(get_db)):
    """Mark a task as completed by the AM for the current period."""
    task = db.get(AMChecklistTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    period = _period_date(task.frequency)
    entry = db.query(AMChecklistEntry).filter(
        AMChecklistEntry.task_id == task_id,
        AMChecklistEntry.location_id == payload.location_id,
        AMChecklistEntry.period_date == period,
    ).first()

    if entry:
        entry.completed = True
        entry.completed_by = payload.completed_by
        entry.completed_at = datetime.utcnow()
        entry.notes = payload.notes
    else:
        entry = AMChecklistEntry(
            task_id=task_id,
            location_id=payload.location_id,
            period_date=period,
            completed=True,
            completed_by=payload.completed_by,
            completed_at=datetime.utcnow(),
            notes=payload.notes,
        )
        db.add(entry)

    db.commit()
    db.refresh(entry)
    return entry


@router.post("/entries/{entry_id}/validate", response_model=EntryOut)
def validate_entry(entry_id: int, payload: ValidateRequest, db: Session = Depends(get_db)):
    """Regional Manager validates a completed task."""
    entry = db.get(AMChecklistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    if not entry.completed:
        raise HTTPException(400, "Cannot validate an incomplete task")
    entry.validated = True
    entry.validated_by = payload.validated_by
    entry.validated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/tasks/{task_id}/undo", response_model=EntryOut)
def undo_complete(task_id: int, location_id: int, db: Session = Depends(get_db)):
    """Un-complete a task (only if not yet validated)."""
    task = db.get(AMChecklistTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    period = _period_date(task.frequency)
    entry = db.query(AMChecklistEntry).filter(
        AMChecklistEntry.task_id == task_id,
        AMChecklistEntry.location_id == location_id,
        AMChecklistEntry.period_date == period,
    ).first()
    if not entry:
        raise HTTPException(404, "No completion record found")
    if entry.validated:
        raise HTTPException(400, "Cannot undo a validated entry")
    entry.completed = False
    entry.completed_by = None
    entry.completed_at = None
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/summary")
def get_summary(location_id: int, db: Session = Depends(get_db)):
    """Progress summary for all frequencies for the current period."""
    summary = {}
    for freq in ChecklistFrequency:
        period = _period_date(freq)
        total = db.query(AMChecklistTask).filter(
            AMChecklistTask.frequency == freq, AMChecklistTask.is_active == True
        ).count()
        completed = db.query(AMChecklistEntry).filter(
            AMChecklistEntry.location_id == location_id,
            AMChecklistEntry.period_date == period,
            AMChecklistEntry.completed == True,
        ).count()
        validated = db.query(AMChecklistEntry).filter(
            AMChecklistEntry.location_id == location_id,
            AMChecklistEntry.period_date == period,
            AMChecklistEntry.validated == True,
        ).count()
        summary[freq.value] = {
            "total": total, "completed": completed, "validated": validated, "period_date": str(period)
        }
    return summary
