from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Any

from app.db.database import get_db
from app.models.ops_visit import OpsVisitReport

router = APIRouter(prefix="/am/ops-visits", tags=["area-manager"])


class SectionItem(BaseModel):
    notes: str | None = None
    due_date: str | None = None   # ISO date string
    person: str | None = None


class OpsVisitCreate(BaseModel):
    location_id: int
    visit_date: date
    visit_time: str | None = None
    visit_done_by: str
    manager_on_duty: str | None = None
    gm_of_store: str | None = None
    store_trading_hours: str | None = None

    # FOH
    foh: dict[str, SectionItem] = {}

    # BOH
    boh: dict[str, SectionItem] = {}

    # Admin
    admin: dict[str, SectionItem] = {}

    # General Property
    general_property: dict[str, SectionItem] = {}

    # Events / Dineplan / Reservations
    events: dict[str, SectionItem] = {}

    # General Discussion
    complaints_resolution: str | None = None
    hr_support: str | None = None

    # Signatures
    mod_signature: str | None = None
    am_signature: str | None = None


class OpsVisitOut(BaseModel):
    id: int
    location_id: int
    visit_date: date
    visit_time: str | None
    visit_done_by: str
    manager_on_duty: str | None
    gm_of_store: str | None
    store_trading_hours: str | None
    foh: dict
    boh: dict
    admin: dict
    general_property: dict
    events: dict
    complaints_resolution: str | None
    hr_support: str | None
    mod_signature: str | None
    am_signature: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class OpsVisitSummary(BaseModel):
    id: int
    location_id: int
    visit_date: date
    visit_done_by: str
    gm_of_store: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[OpsVisitSummary])
def list_visits(location_id: int, limit: int = 30, db: Session = Depends(get_db)):
    return (
        db.query(OpsVisitReport)
        .filter(OpsVisitReport.location_id == location_id)
        .order_by(OpsVisitReport.visit_date.desc())
        .limit(limit)
        .all()
    )


@router.post("/", response_model=OpsVisitOut, status_code=201)
def create_visit(payload: OpsVisitCreate, db: Session = Depends(get_db)):
    report = OpsVisitReport(
        location_id=payload.location_id,
        visit_date=payload.visit_date,
        visit_time=payload.visit_time,
        visit_done_by=payload.visit_done_by,
        manager_on_duty=payload.manager_on_duty,
        gm_of_store=payload.gm_of_store,
        store_trading_hours=payload.store_trading_hours,
        foh={k: v.model_dump() for k, v in payload.foh.items()},
        boh={k: v.model_dump() for k, v in payload.boh.items()},
        admin={k: v.model_dump() for k, v in payload.admin.items()},
        general_property={k: v.model_dump() for k, v in payload.general_property.items()},
        events={k: v.model_dump() for k, v in payload.events.items()},
        complaints_resolution=payload.complaints_resolution,
        hr_support=payload.hr_support,
        mod_signature=payload.mod_signature,
        am_signature=payload.am_signature,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/{report_id}", response_model=OpsVisitOut)
def get_visit(report_id: int, db: Session = Depends(get_db)):
    report = db.get(OpsVisitReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report
