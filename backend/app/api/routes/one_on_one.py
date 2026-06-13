from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.one_on_one import OneOnOneMeeting

router = APIRouter(prefix="/am/one-on-ones", tags=["area-manager"])


class OneOnOneCreate(BaseModel):
    location_id: int
    team_member_name: str
    area_manager_name: str
    meeting_date: date
    q1_experience: str | None = None
    q2_improvements: str | None = None
    q3_concerns: str | None = None
    q4_growth_next_year: str | None = None
    q5_long_term_goals: str | None = None
    q6_mobility: str | None = None
    q7_workplace_issues: str | None = None
    q8_training: str | None = None
    q9_additional_notes: str | None = None
    team_member_signature: str | None = None
    am_signature: str | None = None


class OneOnOneOut(BaseModel):
    id: int
    location_id: int
    team_member_name: str
    area_manager_name: str
    meeting_date: date
    q1_experience: str | None
    q2_improvements: str | None
    q3_concerns: str | None
    q4_growth_next_year: str | None
    q5_long_term_goals: str | None
    q6_mobility: str | None
    q7_workplace_issues: str | None
    q8_training: str | None
    q9_additional_notes: str | None
    team_member_signature: str | None
    am_signature: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class OneOnOneSummary(BaseModel):
    id: int
    team_member_name: str
    area_manager_name: str
    meeting_date: date
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[OneOnOneSummary])
def list_meetings(location_id: int, limit: int = 50, db: Session = Depends(get_db)):
    return (
        db.query(OneOnOneMeeting)
        .filter(OneOnOneMeeting.location_id == location_id)
        .order_by(OneOnOneMeeting.meeting_date.desc())
        .limit(limit)
        .all()
    )


@router.post("/", response_model=OneOnOneOut, status_code=201)
def create_meeting(payload: OneOnOneCreate, db: Session = Depends(get_db)):
    meeting = OneOnOneMeeting(**payload.model_dump())
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=OneOnOneOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.get(OneOnOneMeeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting
