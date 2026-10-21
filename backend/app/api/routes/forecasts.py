"""Sales forecast runs, manager adjustments, accuracy and the readiness gate (Feature 4).

Reads are scoped to the caller's org subtree (404 for a record outside it).
Writes return 403 so the caller learns the action is not allowed.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user, get_subtree_ids
from app.db.database import get_db
from app.models.forecast import ForecastLine, ForecastRun
from app.models.user import User
from app.services.forecast_service import (
    ForecastError, accuracy, adjust_line, run_forecast,
)
from app.services.readiness import is_ready, readiness

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RunCreateIn(BaseModel):
    org_unit_id: int
    start_date: date
    horizon_days: int = Field(default=14, ge=1, le=90)


class LineAdjustIn(BaseModel):
    adjusted_qty: float | None = Field(default=None, ge=0)  # null clears the override
    adjustment_note: str | None = Field(default=None, max_length=500)


class LineOut(BaseModel):
    id: int
    business_date: date
    menu_item_id: int
    baseline_qty: float
    adjusted_qty: float | None
    effective_qty: float
    adjusted_by: str | None
    adjustment_note: str | None

    @classmethod
    def from_line(cls, line: ForecastLine) -> "LineOut":
        return cls(
            id=line.id,
            business_date=line.business_date,
            menu_item_id=line.menu_item_id,
            baseline_qty=float(line.baseline_qty),
            adjusted_qty=float(line.adjusted_qty) if line.adjusted_qty is not None else None,
            effective_qty=float(line.effective_qty),
            adjusted_by=line.adjusted_by,
            adjustment_note=line.adjustment_note,
        )


class RunSummaryOut(BaseModel):
    id: int
    org_unit_id: int
    run_date: date
    method: str
    horizon_days: int
    history_days: int
    created_at: datetime
    created_by: str | None


class RunOut(RunSummaryOut):
    lines: list[LineOut]

    @classmethod
    def from_run(cls, run: ForecastRun) -> "RunOut":
        return cls(**_summary(run).model_dump(), lines=[LineOut.from_line(l) for l in run.lines])


class CheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class ReadinessOut(BaseModel):
    org_unit_id: int
    as_of: date
    ready: bool
    checks: list[CheckOut]


class AccuracyOut(BaseModel):
    window_start: str
    window_end: str
    days_compared: int
    item_days: int
    item_days_with_sales: int
    mape: float | None
    wape: float | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summary(run: ForecastRun) -> RunSummaryOut:
    return RunSummaryOut(
        id=run.id, org_unit_id=run.org_unit_id, run_date=run.run_date, method=run.method,
        horizon_days=run.horizon_days, history_days=run.history_days,
        created_at=run.created_at, created_by=run.created_by,
    )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ForecastError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _run_for_read(db: Session, run_id: int, user: User) -> ForecastRun:
    run = db.get(ForecastRun, run_id)
    if run is None or run.org_unit_id not in get_subtree_ids(db, user.org_unit_id):
        raise HTTPException(404, "Forecast run not found")
    return run


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/runs", response_model=RunOut, status_code=201)
def create_run(
    body: RunCreateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=body.org_unit_id, current_user=current_user, db=db)
    run = _call(
        run_forecast, db, body.org_unit_id, body.start_date, body.horizon_days,
        created_by=current_user.name, actor=current_user,
    )
    return RunOut.from_run(run)


@router.get("/runs", response_model=list[RunSummaryOut])
def list_runs(
    org_unit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=current_user, db=db)
    runs = db.execute(
        select(ForecastRun).where(ForecastRun.org_unit_id == org_unit_id).order_by(ForecastRun.id.desc())
    ).scalars()
    return [_summary(run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return RunOut.from_run(_run_for_read(db, run_id, current_user))


@router.patch("/lines/{line_id}", response_model=LineOut)
def adjust_forecast_line(
    line_id: int,
    body: LineAdjustIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    line = db.get(ForecastLine, line_id)
    if line is None:
        raise HTTPException(404, "Forecast line not found")
    if line.forecast_run.org_unit_id not in get_subtree_ids(db, current_user.org_unit_id):
        raise HTTPException(403, "Access to this org unit is not allowed")
    updated = _call(adjust_line, db, line_id, body.adjusted_qty, body.adjustment_note, current_user)
    return LineOut.from_line(updated)


@router.get("/accuracy", response_model=AccuracyOut | None)
def get_accuracy(
    org_unit_id: int,
    days: int = Query(default=14, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=current_user, db=db)
    result = _call(accuracy, db, org_unit_id, days)
    return AccuracyOut(**result) if result is not None else None


@router.get("/readiness", response_model=ReadinessOut)
def get_readiness(
    org_unit_id: int,
    as_of: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=current_user, db=db)
    as_of = as_of or date.today()
    checks = readiness(db, org_unit_id, as_of)
    return ReadinessOut(
        org_unit_id=org_unit_id, as_of=as_of, ready=is_ready(checks),
        checks=[CheckOut(**c) for c in checks],
    )
