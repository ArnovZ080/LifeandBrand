"""
Audit trail helpers (Feature 3).

record() adds an AuditEvent to the caller's session and does NOT commit. Each
service calls it right before its own commit, so the audit row and the change
it describes succeed or fail together.

model_snapshot() turns a mapped row into a JSON-safe dict of its column values.
Credential columns (hashed_password and similar) are always left out.

diff() keeps only the keys whose values differ. Update flows use it to store
compact before/after dicts.

query_events() and iter_event_batches() return newest first. Callers pass the
org units the user may see (get_accessible_org_unit_ids). Events with no org
unit are visible only to their actor.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterator

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect as sa_inspect

from app.models.audit import AuditEvent
from app.models.user import User

ACTOR_NAME_MAX = 120
ENTITY_ID_MAX = 60
SECRET_MARKERS = ("password", "secret", "token", "api_key")
EXPORT_BATCH = 500


def _is_secret(column_key: str) -> bool:
    lowered = column_key.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _plain(value):
    """Convert one column value to something json.dumps accepts."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return str(value)


def model_snapshot(instance) -> dict:
    """Column values of a mapped instance, with secrets removed.

    Relationships are not included; a caller that wants children adds them.
    """
    mapper = sa_inspect(instance).mapper
    return {
        attr.key: _plain(getattr(instance, attr.key))
        for attr in mapper.column_attrs
        if not _is_secret(attr.key)
    }


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """(before, after) restricted to the keys whose values differ.

    A key present on only one side counts as changed; the missing side is None.
    """
    changed = sorted(
        key for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    )
    return (
        {key: before.get(key) for key in changed},
        {key: after.get(key) for key in changed},
    )


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def record(
    db: Session,
    *,
    actor: User | None,
    actor_name: str | None = None,
    entity_type: str,
    entity_id,
    action: str,
    org_unit_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    summary: str | None = None,
) -> AuditEvent:
    """Stage one audit event on the session. The caller commits.

    actor_name is the name given in the request. It falls back to the actor's
    own name, and stays None for unauthenticated flows.
    """
    name = actor_name if actor_name else (actor.name if actor is not None else None)
    event = AuditEvent(
        actor_user_id=actor.id if actor is not None else None,
        actor_name=_clip(name, ACTOR_NAME_MAX),
        actor_role=actor.role.value if actor is not None and actor.role is not None else None,
        org_unit_id=org_unit_id,
        entity_type=entity_type,
        entity_id=_clip(str(entity_id), ENTITY_ID_MAX),
        action=action,
        before=before,
        after=after,
        summary=summary,
    )
    db.add(event)
    return event


# ── Reading ───────────────────────────────────────────────────────────────────

@dataclass
class AuditFilters:
    entity_type: str | None = None
    entity_id: str | None = None
    action: str | None = None
    actor_user_id: int | None = None
    org_unit_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None


def _scoped(query, user: User, allowed_unit_ids: list[int], filters: AuditFilters):
    """Apply the visibility rule and the optional filters to a select."""
    query = query.where(or_(
        AuditEvent.org_unit_id.in_(allowed_unit_ids),
        and_(AuditEvent.org_unit_id.is_(None), AuditEvent.actor_user_id == user.id),
    ))
    if filters.entity_type is not None:
        query = query.where(AuditEvent.entity_type == filters.entity_type)
    if filters.entity_id is not None:
        query = query.where(AuditEvent.entity_id == filters.entity_id)
    if filters.action is not None:
        query = query.where(AuditEvent.action == filters.action)
    if filters.actor_user_id is not None:
        query = query.where(AuditEvent.actor_user_id == filters.actor_user_id)
    if filters.org_unit_id is not None:
        query = query.where(AuditEvent.org_unit_id == filters.org_unit_id)
    if filters.date_from is not None:
        query = query.where(AuditEvent.occurred_at >= datetime.combine(filters.date_from, time.min))
    if filters.date_to is not None:
        query = query.where(
            AuditEvent.occurred_at < datetime.combine(filters.date_to + timedelta(days=1), time.min)
        )
    return query


def query_events(
    db: Session,
    user: User,
    allowed_unit_ids: list[int],
    filters: AuditFilters,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    """One page of events, newest first. allowed_unit_ids comes from get_accessible_org_unit_ids."""
    query = _scoped(select(AuditEvent), user, allowed_unit_ids, filters)
    query = query.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


def iter_event_batches(
    db: Session,
    user: User,
    allowed_unit_ids: list[int],
    filters: AuditFilters,
    *,
    batch_size: int = EXPORT_BATCH,
) -> Iterator[list[AuditEvent]]:
    """All matching events, newest first, in keyset-paginated batches (for streaming exports)."""
    last_id: int | None = None
    while True:
        query = _scoped(select(AuditEvent), user, allowed_unit_ids, filters)
        if last_id is not None:
            query = query.where(AuditEvent.id < last_id)
        batch = list(db.execute(query.order_by(AuditEvent.id.desc()).limit(batch_size)).scalars())
        if not batch:
            return
        yield batch
        last_id = batch[-1].id
