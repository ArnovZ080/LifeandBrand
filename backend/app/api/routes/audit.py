"""Audit log read and export endpoints (Feature 3).

Reads are scoped to the caller's org subtree, with unit-less events visible only
to their actor. CSV export is restricted to senior roles.
"""
import csv
import io
import json
from datetime import date, datetime
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user
from app.db.database import get_db
from app.models.audit import AuditEvent
from app.models.user import User, UserRole
from app.services import audit_service
from app.services.audit_service import AuditFilters

router = APIRouter(prefix="/audit", tags=["audit"])

EXPORT_ROLES = {UserRole.MD, UserRole.CEO, UserRole.NATIONAL_OPS, UserRole.REGIONAL_MANAGER}
CSV_COLUMNS = [
    "id", "occurred_at", "actor_user_id", "actor_name", "actor_role", "org_unit_id",
    "entity_type", "entity_id", "action", "summary", "before", "after",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: int | None
    actor_name: str | None
    actor_role: str | None
    org_unit_id: int | None
    entity_type: str
    entity_id: str
    action: str
    before: Any | None
    after: Any | None
    summary: str | None

    @classmethod
    def from_event(cls, e: AuditEvent) -> "AuditEventOut":
        return cls(
            id=e.id, occurred_at=e.occurred_at, actor_user_id=e.actor_user_id,
            actor_name=e.actor_name, actor_role=e.actor_role, org_unit_id=e.org_unit_id,
            entity_type=e.entity_type, entity_id=e.entity_id, action=e.action,
            before=e.before, after=e.after, summary=e.summary,
        )


def _filters(
    entity_type: str | None,
    entity_id: str | None,
    action: str | None,
    actor_user_id: int | None,
    org_unit_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> AuditFilters:
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(400, "date_to must be on or after date_from")
    return AuditFilters(
        entity_type=entity_type, entity_id=entity_id, action=action,
        actor_user_id=actor_user_id, org_unit_id=org_unit_id,
        date_from=date_from, date_to=date_to,
    )


def _allowed_units(db: Session, user: User, org_unit_id: int | None) -> list[int]:
    """Caller's org subtree, or just the requested unit. 403 outside the subtree."""
    return get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=user, db=db)


def _csv_cell(value) -> str:
    """Render a value for CSV. Text that a spreadsheet would read as a formula gets a leading quote."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str)
    elif isinstance(value, datetime):
        text = value.isoformat()
    else:
        text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    return text


def _csv_stream(db: Session, user: User, allowed: list[int], filters: AuditFilters) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return chunk

    writer.writerow(CSV_COLUMNS)
    yield flush()
    try:
        for batch in audit_service.iter_event_batches(db, user, allowed, filters):
            for e in batch:
                writer.writerow([
                    _csv_cell(e.id), _csv_cell(e.occurred_at), _csv_cell(e.actor_user_id),
                    _csv_cell(e.actor_name), _csv_cell(e.actor_role), _csv_cell(e.org_unit_id),
                    _csv_cell(e.entity_type), _csv_cell(e.entity_id), _csv_cell(e.action),
                    _csv_cell(e.summary), _csv_cell(e.before), _csv_cell(e.after),
                ])
            yield flush()
    finally:
        # The request's session is closed before a streamed body is iterated, so the
        # generator reopens it on first use and must release it itself.
        db.close()


@router.get("/", response_model=list[AuditEventOut])
def list_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    org_unit_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = _filters(entity_type, entity_id, action, actor_user_id, org_unit_id, date_from, date_to)
    allowed = _allowed_units(db, current_user, org_unit_id)
    events = audit_service.query_events(
        db, current_user, allowed, filters, limit=limit, offset=offset,
    )
    return [AuditEventOut.from_event(e) for e in events]


@router.get("/export.csv")
def export_audit_csv(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    org_unit_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in EXPORT_ROLES:
        raise HTTPException(403, "Your role cannot export the audit log")
    filters = _filters(entity_type, entity_id, action, actor_user_id, org_unit_id, date_from, date_to)
    allowed = _allowed_units(db, current_user, org_unit_id)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        _csv_stream(db, current_user, allowed, filters),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-log-{stamp}.csv"'},
    )
