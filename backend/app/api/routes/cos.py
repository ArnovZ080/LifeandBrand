"""COS variance endpoints (Phase 2)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models import Item
from app.models.cos_flag import CosDismissal, CosFlag
from app.models.user import User
from app.services.cos_service import compute_variance

router = APIRouter(prefix="/cos", tags=["cos"])

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class VarianceSummary(BaseModel):
    actual_cos_pct: float | None
    theoretical_cos_pct: float | None
    variance_pct: float | None
    actual_usage_value: float | None
    theoretical_usage_value: float | None


class FlagOut(BaseModel):
    id: int
    item_name: str
    actual_qty: float | None
    theoretical_qty: float | None
    variance_qty: float | None
    variance_value: float | None
    cause: str | None
    status: str


class VarianceOut(BaseModel):
    summary: VarianceSummary
    flags: list[FlagOut]


class DismissIn(BaseModel):
    reason: str
    dismissed_by: str | None = None


def _flag_out(flag: CosFlag, item_name: str) -> FlagOut:
    return FlagOut(
        id=flag.id,
        item_name=item_name,
        actual_qty=float(flag.actual_qty) if flag.actual_qty is not None else None,
        theoretical_qty=float(flag.theoretical_qty) if flag.theoretical_qty is not None else None,
        variance_qty=float(flag.variance_qty) if flag.variance_qty is not None else None,
        variance_value=float(flag.variance_value) if flag.variance_value is not None else None,
        cause=flag.cause.value if flag.cause is not None else None,
        status=flag.status,
    )


@router.get("/variance", response_model=VarianceOut)
def variance(
    org_unit_id: int,
    period: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not PERIOD_RE.match(period):
        raise HTTPException(400, "period must be YYYY-MM")
    result = compute_variance(db, org_unit_id, period)
    flags: list[CosFlag] = result["flags"]
    names = {
        i.id: i.name
        for i in db.query(Item).filter(Item.id.in_({f.item_id for f in flags})).all()
    } if flags else {}
    return VarianceOut(
        summary=VarianceSummary(**result["summary"]),
        flags=[_flag_out(f, names.get(f.item_id, f"item #{f.item_id}")) for f in flags],
    )


@router.post("/flags/{flag_id}/dismiss", response_model=FlagOut)
def dismiss_flag(
    flag_id: int,
    payload: DismissIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    flag = db.get(CosFlag, flag_id)
    if flag is None:
        raise HTTPException(404, "Flag not found")
    if not payload.reason.strip():
        raise HTTPException(400, "A dismissal reason is required")
    db.add(CosDismissal(
        flag_id=flag.id,
        reason=payload.reason.strip(),
        dismissed_by=payload.dismissed_by or getattr(current_user, "email", None),
    ))
    flag.status = "dismissed"
    db.commit()
    db.refresh(flag)
    item = db.get(Item, flag.item_id)
    return _flag_out(flag, item.name if item else f"item #{flag.item_id}")
