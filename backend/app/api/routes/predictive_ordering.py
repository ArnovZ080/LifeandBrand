"""Predictive ordering: suggested orders and draft requisitions (Feature 4).

Nothing here submits an order. create-drafts makes DRAFT requisitions only; a
person submits them through the requisition approval flow.

Role check: requisition creation has no role gate, only the org-subtree check,
and this route applies the same check.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.forecast_service import ForecastError
from app.services.predictive_ordering import (
    NotReady, Suggestion, create_draft, suggest_order,
)

router = APIRouter(prefix="/predictive-orders", tags=["predictive-orders"])


class SuggestIn(BaseModel):
    org_unit_id: int
    coverage_days: int = Field(ge=1, le=60)
    delivery_date: date
    supplier_id: int | None = None
    stock_overrides: dict[int, float] | None = None
    override: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class CheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class SuggestedLineOut(BaseModel):
    item_id: int
    item_name: str
    supplier_id: int
    required_qty: float
    on_hand_qty: float
    suggested_qty: float
    last_order_qty: float | None
    four_week_avg_order_qty: float


class UnassignedOut(BaseModel):
    item_id: int
    item_name: str
    need_qty: float
    reason: str


class SuggestionOut(BaseModel):
    org_unit_id: int
    forecast_run_id: int
    coverage_days: int
    delivery_date: date
    as_of: date
    overridden: bool
    override_reason: str | None
    stock_overrides_applied: list[int]
    readiness: list[CheckOut]
    lines: list[SuggestedLineOut]
    unassigned: list[UnassignedOut]

    @classmethod
    def from_suggestion(cls, s: Suggestion) -> "SuggestionOut":
        return cls(
            org_unit_id=s.org_unit_id, forecast_run_id=s.forecast_run_id,
            coverage_days=s.coverage_days, delivery_date=s.delivery_date, as_of=s.as_of,
            overridden=s.overridden, override_reason=s.override_reason,
            stock_overrides_applied=s.stock_overrides_applied,
            readiness=[CheckOut(**c) for c in s.readiness],
            lines=[
                SuggestedLineOut(
                    item_id=l.item_id, item_name=l.item_name, supplier_id=l.supplier_id,
                    required_qty=float(l.required_qty), on_hand_qty=float(l.on_hand_qty),
                    suggested_qty=float(l.suggested_qty),
                    last_order_qty=float(l.last_order_qty) if l.last_order_qty is not None else None,
                    four_week_avg_order_qty=float(l.four_week_avg_order_qty),
                )
                for l in s.lines
            ],
            unassigned=[
                UnassignedOut(item_id=u.item_id, item_name=u.item_name,
                              need_qty=float(u.need_qty), reason=u.reason)
                for u in s.unassigned
            ],
        )


class DraftOut(BaseModel):
    id: int
    requisition_number: str
    supplier_id: int | None
    status: str
    line_count: int


class DraftsOut(BaseModel):
    requisitions: list[DraftOut]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotReady as exc:
        raise HTTPException(409, detail={"message": str(exc), "checks": exc.checks})
    except ForecastError as exc:
        raise HTTPException(409, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _suggest(body: SuggestIn, current_user: User, db: Session) -> Suggestion:
    get_accessible_org_unit_ids(requested_org_unit_id=body.org_unit_id, current_user=current_user, db=db)
    return _call(
        suggest_order, db, body.org_unit_id, body.coverage_days, body.delivery_date,
        supplier_id=body.supplier_id, stock_overrides=body.stock_overrides,
        override=body.override, override_reason=body.override_reason, actor=current_user,
    )


@router.post("/suggest", response_model=SuggestionOut)
def suggest(
    body: SuggestIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return SuggestionOut.from_suggestion(_suggest(body, current_user, db))


@router.post("/suggest/create-drafts", response_model=DraftsOut, status_code=201)
def create_drafts(
    body: SuggestIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suggestion = _suggest(body, current_user, db)
    requisitions = _call(create_draft, db, suggestion, current_user.name, actor=current_user)
    return DraftsOut(requisitions=[
        DraftOut(
            id=r.id, requisition_number=r.requisition_number, supplier_id=r.supplier_id,
            status=r.status.value, line_count=len(r.lines),
        )
        for r in requisitions
    ])
