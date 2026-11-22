"""Shopping-list draft creation is all or nothing.

Reuses the par/shopping-list fixtures. Failures are injected by replacing
requisition_service.stage_draft so that the second supplier group raises.
Assertions read through a new session. The test engine uses a StaticPool, so
that session shares the connection; a missing rollback would still leave
flushed rows visible and fail the count checks.
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import AuditEvent
from app.models.requisition import Requisition, RequisitionStatus
from app.services import requisition_service
from app.services.approval_service import ConflictError
from app.services.par_service import create_draft_requisitions, upsert_par
from app.services.requisition_service import LineSpec
from tests.test_par_and_shopping_list import _stock, db, world  # noqa: F401  (pytest fixtures)


def _stock_two_groups(db, world):
    """Steak (Meat Co) and lettuce (Veg Co) both fall to par at site A."""
    _stock(db, world["site_a"], world["steak"], 0)
    _stock(db, world["site_a"], world["lettuce"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    upsert_par(db, world["site_a"], world["lettuce"].id, 12, 2, world["gm_a"])


def _fresh_counts(db):
    """Counts read through a new session, so only committed state is visible."""
    fresh = sessionmaker(bind=db.get_bind())()
    try:
        requisitions = fresh.execute(select(func.count()).select_from(Requisition)).scalar_one()
        audit_total = fresh.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
        draft_audit = fresh.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.entity_type.in_(["requisition", "shopping_list"])
            )
        ).scalar_one()
        return requisitions, audit_total, draft_audit
    finally:
        fresh.close()


def test_happy_path_creates_one_draft_per_group_and_writes_audit(db, world):
    _stock_two_groups(db, world)

    created = create_draft_requisitions(db, world["site_a"].id, world["gm_a"])

    assert len(created) == 2
    numbers = [r.requisition_number for r in created]
    assert len(set(numbers)) == 2  # numbering stays unique within the transaction
    assert all(r.status == RequisitionStatus.DRAFT for r in created)
    assert _fresh_counts(db)[0] == 2
    fresh = sessionmaker(bind=db.get_bind())()
    try:
        req_events = fresh.execute(
            select(AuditEvent).where(AuditEvent.entity_type == "requisition", AuditEvent.action == "create")
        ).scalars().all()
        shopping_events = fresh.execute(
            select(AuditEvent).where(AuditEvent.entity_type == "shopping_list", AuditEvent.action == "create_drafts")
        ).scalars().all()
        assert len(req_events) == 2
        assert len(shopping_events) == 1
        assert sorted(shopping_events[0].after["requisitions"]) == sorted(numbers)
    finally:
        fresh.close()


@pytest.mark.parametrize("failure, expected", [
    (ValueError("bad line"), ValueError),
    (IntegrityError("INSERT", {}, Exception("duplicate requisition_number")), ConflictError),
])
def test_failure_on_second_group_leaves_nothing_behind(db, world, monkeypatch, failure, expected):
    _stock_two_groups(db, world)
    before = _fresh_counts(db)

    real_stage = requisition_service.stage_draft
    calls = {"n": 0}

    def fail_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise failure
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(requisition_service, "stage_draft", fail_on_second)

    with pytest.raises(expected):
        create_draft_requisitions(db, world["site_a"].id, world["gm_a"])

    assert calls["n"] == 2  # the first group was staged before the failure
    after = _fresh_counts(db)
    assert after[0] == 0  # no requisitions, including the first group's draft
    assert after[1] == before[1]  # no audit rows at all, requisition or shopping list
    assert after[2] == 0

    # The session is usable again after the failure.
    monkeypatch.setattr(requisition_service, "stage_draft", real_stage)
    created = create_draft_requisitions(db, world["site_a"].id, world["gm_a"])
    assert len(created) == 2


def test_public_create_draft_still_commits_on_its_own(db, world):
    _stock_two_groups(db, world)
    draft = requisition_service.create_draft(
        db, org_unit_id=world["site_a"].id,
        lines=[LineSpec(item_id=world["steak"].id, quantity=3)],
        supplier_id=world["meat"].id, notes="single", requested_by="GM A", actor=world["gm_a"],
    )
    db.rollback()  # would discard anything uncommitted

    assert _fresh_counts(db)[0] == 1
    fresh = sessionmaker(bind=db.get_bind())()
    try:
        row = fresh.get(Requisition, draft.id)
        assert row is not None
        assert row.requisition_number == draft.requisition_number
        assert row.status == RequisitionStatus.DRAFT
        assert len(row.lines) == 1
    finally:
        fresh.close()
