"""
Append-only audit log (Feature 3).

Every state-changing flow writes one AuditEvent in the same transaction as the
change (see services/audit_service.record). Rows are never updated or deleted.
Three layers enforce that:

  1. ORM: before_update / before_delete mapper listeners on AuditEvent.
  2. ORM bulk statements: a do_orm_execute hook refuses bulk UPDATE/DELETE
     that targets audit_events (those skip the mapper listeners).
  3. Database: migration 0007 installs a Postgres trigger that refuses UPDATE,
     DELETE and TRUNCATE on audit_events.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, event,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.database import Base


class AuditLogImmutableError(RuntimeError):
    """Raised when code tries to change or remove an audit event."""


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    # BigInteger in Postgres; SQLite only autoincrements a plain INTEGER primary key.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True,
    )
    actor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    org_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("org_units.id"), nullable=True, index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    before: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


def _refuse(*_args, **_kwargs) -> None:
    raise AuditLogImmutableError("Audit events are append-only and cannot be changed or deleted")


event.listen(AuditEvent, "before_update", _refuse)
event.listen(AuditEvent, "before_delete", _refuse)


@event.listens_for(Session, "do_orm_execute")
def _refuse_bulk_changes(orm_execute_state) -> None:
    """Bulk query.update() / query.delete() skip mapper events, so refuse them here."""
    if not (orm_execute_state.is_update or orm_execute_state.is_delete):
        return
    if any(mapper.class_ is AuditEvent for mapper in orm_execute_state.all_mappers):
        raise AuditLogImmutableError("Audit events are append-only; bulk changes are refused")
