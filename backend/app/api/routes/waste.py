"""Wastage logging and summary endpoints (Feature 1)."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.models.waste import WasteEvent, WasteReason
from app.services.waste_service import log_waste, waste_summary

router = APIRouter(prefix="/waste", tags=["waste"])


class WasteLogIn(BaseModel):
    org_unit_id: int
    item_id: int
    quantity: float = Field(gt=0)
    reason: WasteReason
    reason_note: str | None = None
    logged_by: str | None = None
    event_date: date | None = None


class WasteEventOut(BaseModel):
    id: int
    org_unit_id: int
    item_id: int
    quantity: float
    reason: WasteReason
    reason_note: str | None
    unit_cost: float | None
    cost_value: float
    logged_by: str | None
    event_date: date
    created_at: datetime

    @classmethod
    def from_event(cls, e: WasteEvent) -> "WasteEventOut":
        return cls(
            id=e.id,
            org_unit_id=e.org_unit_id,
            item_id=e.item_id,
            quantity=float(e.quantity),
            reason=e.reason,
            reason_note=e.reason_note,
            unit_cost=float(e.unit_cost) if e.unit_cost is not None else None,
            cost_value=float(e.cost_value or 0),
            logged_by=e.logged_by,
            event_date=e.event_date,
            created_at=e.created_at,
        )


class ReasonTotalOut(BaseModel):
    reason: str
    events: int
    quantity: float
    cost_value: float


class ItemTotalOut(BaseModel):
    item_id: int
    item_name: str
    quantity: float
    cost_value: float


class WasteSummaryOut(BaseModel):
    org_unit_id: int
    date_from: date
    date_to: date
    events: int
    total_cost_value: float
    by_reason: list[ReasonTotalOut]
    by_item: list[ItemTotalOut]


@router.post("/", response_model=WasteEventOut, status_code=201)
def log_waste_event(
    payload: WasteLogIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        event = log_waste(
            db,
            org_unit_id=payload.org_unit_id,
            item_id=payload.item_id,
            quantity=payload.quantity,
            reason=payload.reason,
            reason_note=payload.reason_note,
            logged_by=payload.logged_by or current_user.email,
            event_date=payload.event_date,
            actor=current_user,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return WasteEventOut.from_event(event)


@router.get("/summary", response_model=WasteSummaryOut)
def get_waste_summary(
    org_unit_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if date_to < date_from:
        raise HTTPException(400, "date_to must be on or after date_from")
    result = waste_summary(db, org_unit_id, date_from, date_to)

    def f(v: Decimal) -> float:
        return float(v)

    return WasteSummaryOut(
        org_unit_id=org_unit_id,
        date_from=date_from,
        date_to=date_to,
        events=result["events"],
        total_cost_value=f(result["total_cost_value"]),
        by_reason=[
            ReasonTotalOut(reason=r["reason"], events=r["events"],
                           quantity=f(r["quantity"]), cost_value=f(r["cost_value"]))
            for r in result["by_reason"]
        ],
        by_item=[
            ItemTotalOut(item_id=i["item_id"], item_name=i["item_name"],
                         quantity=f(i["quantity"]), cost_value=f(i["cost_value"]))
            for i in result["by_item"]
        ],
    )
