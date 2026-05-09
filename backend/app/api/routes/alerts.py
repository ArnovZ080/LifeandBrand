from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.contact import LocationContact, NotificationChannel
from app.models.alert import ExpiryAlert, AlertStatus
from app.services.alert_engine import run_alert_check, AlertResult

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Contact schemas ────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    location_id: int
    name: str
    role: str | None = None
    email: str | None = None
    whatsapp_number: str | None = None
    teams_webhook_url: str | None = None
    # Comma-separated: "email,whatsapp"
    active_channels: str = "email"
    # Comma-separated dept names: "kitchen,floor"
    departments_subscribed: str = ""
    quiet_hours_start: int = 22
    quiet_hours_end: int = 7


class ContactOut(BaseModel):
    id: int
    location_id: int
    name: str
    role: str | None
    email: str | None
    whatsapp_number: str | None
    active_channels: str
    departments_subscribed: str
    quiet_hours_start: int
    quiet_hours_end: int
    is_active: bool

    class Config:
        from_attributes = True


# ── Alert history schemas ──────────────────────────────────────────────────────

class AlertHistoryOut(BaseModel):
    id: int
    batch_id: int
    item_name: str
    batch_reference: str | None
    contact_name: str
    alert_level: int
    channel: str
    status: str
    message_preview: str | None
    sent_at: datetime

    class Config:
        from_attributes = True


class TriggerResult(BaseModel):
    alerts_sent: int
    alerts_failed: int
    alerts_suppressed: int
    detail: list[dict]


# ── Contact management ─────────────────────────────────────────────────────────

@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(location_id: int, db: Session = Depends(get_db)):
    return (
        db.query(LocationContact)
        .filter(LocationContact.location_id == location_id, LocationContact.is_active == True)
        .order_by(LocationContact.name)
        .all()
    )


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    if not any([payload.email, payload.whatsapp_number, payload.teams_webhook_url]):
        raise HTTPException(400, "At least one contact channel (email, WhatsApp, or Teams) is required")
    contact = LocationContact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, payload: ContactCreate, db: Session = Depends(get_db)):
    contact = db.get(LocationContact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=204)
def deactivate_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(LocationContact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    contact.is_active = False
    db.commit()


# ── Alert trigger ──────────────────────────────────────────────────────────────

@router.post("/trigger", response_model=TriggerResult)
def trigger_alerts(location_id: int | None = None, db: Session = Depends(get_db)):
    """
    Run the expiry alert check and send notifications.
    Call this at shift start via cron (e.g. 06:30 and 14:00 daily).
    Can also be triggered manually from the dashboard.
    """
    results = run_alert_check(db, location_id=location_id)
    sent = [r for r in results if r.status == "sent"]
    failed = [r for r in results if r.status == "failed"]
    suppressed = [r for r in results if r.status == "suppressed"]

    return TriggerResult(
        alerts_sent=len(sent),
        alerts_failed=len(failed),
        alerts_suppressed=len(suppressed),
        detail=[
            {
                "item": r.item_name,
                "batch": r.batch_reference,
                "contact": r.contact_name,
                "channel": r.channel,
                "status": r.status,
            }
            for r in results
        ],
    )


# ── Alert history ──────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[AlertHistoryOut])
def get_alert_history(
    location_id: int,
    days: int = 7,
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(ExpiryAlert)
        .join(LocationContact, LocationContact.id == ExpiryAlert.contact_id)
        .filter(
            LocationContact.location_id == location_id,
            ExpiryAlert.sent_at >= since,
        )
        .order_by(ExpiryAlert.sent_at.desc())
        .limit(200)
        .all()
    )
    return [
        AlertHistoryOut(
            id=r.id,
            batch_id=r.batch_id,
            item_name=r.batch.item.name,
            batch_reference=r.batch.batch_reference,
            contact_name=r.contact.name,
            alert_level=r.alert_level,
            channel=r.channel.value,
            status=r.status.value,
            message_preview=r.message_preview,
            sent_at=r.sent_at,
        )
        for r in rows
    ]
