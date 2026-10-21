"""Tests for the append-only audit log (Feature 3).

Runs on an in-memory SQLite engine. The append-only guarantee that matters
most (the Postgres trigger) is installed by migration 0007 and checked against
a real Postgres server separately (see the report).
"""
import csv
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent, AuditLogImmutableError, Item, OrgTier, OrgUnit, UnitOfMeasure, User, UserRole,
)
from app.models.requisition import RequisitionStatus
from app.services import audit_service
from app.services.requisition_service import LineSpec, create_draft, submit
from app.services.waste_service import log_waste
from app.models.waste import WasteReason

SECRET_HASH = "$2b$12$secret-hash-that-must-never-be-audited"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def world(db):
    """National > North (site A, site B) and South (site C). Items: steak (4.50), salt (no cost)."""
    uom = UnitOfMeasure(name="each", abbreviation="ea")
    db.add(uom)
    db.flush()

    national = OrgUnit(name="National", tier=OrgTier.NATIONAL)
    db.add(national)
    db.flush()
    north = OrgUnit(name="North", tier=OrgTier.AREA, parent_id=national.id)
    south = OrgUnit(name="South", tier=OrgTier.AREA, parent_id=national.id)
    db.add_all([north, south])
    db.flush()
    site_a = OrgUnit(name="Site A", tier=OrgTier.SITE, parent_id=north.id)
    site_c = OrgUnit(name="Site C", tier=OrgTier.SITE, parent_id=south.id)
    db.add_all([site_a, site_c])
    db.flush()

    def user(email, name, role, unit):
        u = User(email=email, hashed_password=SECRET_HASH, name=name, role=role, org_unit_id=unit.id)
        db.add(u)
        db.flush()
        return u

    users = {
        "gm_a": user("gm.a@example.test", "GM A", UserRole.SITE_GM, site_a),
        "am_north": user("am.north@example.test", "AM North", UserRole.AREA_MANAGER, north),
        "md": user("md@example.test", "MD", UserRole.MD, national),
        "rm": user("rm@example.test", "RM", UserRole.REGIONAL_MANAGER, national),
    }

    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id, unit_cost=4.50)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id, unit_cost=None)
    db.add_all([steak, salt])
    db.commit()
    return {"national": national, "north": north, "south": south,
            "site_a": site_a, "site_c": site_c, "steak": steak, "salt": salt, **users}


@pytest.fixture
def api(db):
    """HTTP client bound to the test session. Auth is swapped per test with as_user."""
    def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


# ── Append-only enforcement ───────────────────────────────────────────────────

def _one_event(db) -> AuditEvent:
    event = audit_service.record(
        db, actor=None, entity_type="thing", entity_id=1, action="create", summary="original",
    )
    db.commit()
    return event


def test_update_of_an_audit_event_is_refused(db):
    event = _one_event(db)
    event.summary = "rewritten"
    with pytest.raises(AuditLogImmutableError):
        db.flush()
    db.rollback()
    assert db.execute(select(AuditEvent.summary)).scalar_one() == "original"


def test_delete_of_an_audit_event_is_refused(db):
    event = _one_event(db)
    db.delete(event)
    with pytest.raises(AuditLogImmutableError):
        db.flush()
    db.rollback()
    assert db.query(AuditEvent).count() == 1


def test_bulk_update_and_delete_are_refused(db):
    _one_event(db)
    with pytest.raises(AuditLogImmutableError):
        db.query(AuditEvent).update({"summary": "rewritten"})
    db.rollback()
    with pytest.raises(AuditLogImmutableError):
        db.query(AuditEvent).delete()
    db.rollback()
    assert db.query(AuditEvent).count() == 1


# ── Recording and snapshots ───────────────────────────────────────────────────

def test_record_writes_one_event_with_before_and_after_and_no_password_hash(db, world):
    gm = world["gm_a"]
    before = audit_service.model_snapshot(gm)
    assert "hashed_password" not in before
    assert SECRET_HASH not in json.dumps(before)

    gm.name = "GM Alpha"
    db.flush()
    changed_before, changed_after = audit_service.diff(before, audit_service.model_snapshot(gm))
    audit_service.record(
        db, actor=world["md"], entity_type="user", entity_id=gm.id, action="update",
        org_unit_id=gm.org_unit_id, before=changed_before, after=changed_after,
        summary="Renamed user",
    )
    db.commit()

    events = db.query(AuditEvent).all()
    assert len(events) == 1
    event = events[0]
    assert event.before == {"name": "GM A"}
    assert event.after == {"name": "GM Alpha"}
    assert event.actor_user_id == world["md"].id
    assert event.actor_name == "MD"
    assert event.actor_role == "md"
    assert SECRET_HASH not in json.dumps([event.before, event.after])


def test_snapshot_converts_enums_dates_and_decimals(db, world):
    event = log_waste(
        db, org_unit_id=world["site_a"].id, item_id=world["steak"].id, quantity=2,
        reason=WasteReason.SPOILAGE, actor=world["gm_a"],
    )
    snap = audit_service.model_snapshot(event)
    assert snap["reason"] == "spoilage"
    assert snap["event_date"] == date.today().isoformat()
    assert snap["cost_value"] == "9.00"


def test_diff_keeps_only_changed_keys():
    before_part, after_part = audit_service.diff({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5})
    assert before_part == {"b": 2, "c": 3}
    assert after_part == {"b": 5, "c": None}


# ── Hooks into existing flows ─────────────────────────────────────────────────

def test_waste_log_writes_an_audit_row(db, world):
    event = log_waste(
        db, org_unit_id=world["site_a"].id, item_id=world["steak"].id, quantity=1.5,
        reason=WasteReason.EXPIRED, logged_by="GM A", actor=world["gm_a"],
    )
    rows = db.query(AuditEvent).filter(AuditEvent.entity_type == "waste_event").all()
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_id == str(event.id)
    assert row.action == "create"
    assert row.org_unit_id == world["site_a"].id
    assert row.actor_user_id == world["gm_a"].id
    assert row.actor_name == "GM A"
    assert row.after["quantity"] == "1.5"


def test_requisition_create_and_submit_each_write_an_audit_row(db, world):
    gm = world["gm_a"]
    requisition = create_draft(
        db, org_unit_id=world["site_a"].id,
        lines=[LineSpec(item_id=world["steak"].id, quantity=2)],
        requested_by="GM A", actor=gm,
    )
    submit(db, requisition, actor=gm)

    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_type == "requisition", AuditEvent.entity_id == str(requisition.id))
        .order_by(AuditEvent.id)
        .all()
    )
    assert [r.action for r in rows] == ["create", "submit"]
    submit_row = rows[1]
    assert submit_row.before["status"] == RequisitionStatus.DRAFT.value
    assert submit_row.after["status"] == RequisitionStatus.APPROVED.value
    assert submit_row.after["total_value"] == "9.00"
    assert all(r.org_unit_id == world["site_a"].id for r in rows)


# ── Scoped reads ──────────────────────────────────────────────────────────────

def _seed_events(db, world):
    log_waste(db, org_unit_id=world["site_a"].id, item_id=world["steak"].id, quantity=1,
              reason=WasteReason.SPOILAGE, actor=world["gm_a"])
    log_waste(db, org_unit_id=world["site_c"].id, item_id=world["steak"].id, quantity=1,
              reason=WasteReason.SPOILAGE)  # no actor: logged in site C
    audit_service.record(db, actor=None, entity_type="system_note", entity_id=0, action="login")
    db.commit()


def test_scoped_query_hides_events_outside_the_callers_org(db, api, world):
    _seed_events(db, world)
    as_user(world["gm_a"])

    response = api.get("/api/v1/audit/")
    assert response.status_code == 200
    rows = response.json()
    assert rows, "site A's own events should be visible"
    assert {r["org_unit_id"] for r in rows} == {world["site_a"].id}
    assert all(r["org_unit_id"] != world["site_c"].id for r in rows)
    assert all(r["entity_type"] != "system_note" for r in rows), "unit-less events are actor-only"


def test_national_user_sees_events_from_every_site(db, api, world):
    _seed_events(db, world)
    as_user(world["md"])
    rows = api.get("/api/v1/audit/", params={"entity_type": "waste_event"}).json()
    assert {r["org_unit_id"] for r in rows} == {world["site_a"].id, world["site_c"].id}


def test_reading_another_units_events_by_org_filter_is_forbidden(db, api, world):
    _seed_events(db, world)
    as_user(world["gm_a"])
    response = api.get("/api/v1/audit/", params={"org_unit_id": world["site_c"].id})
    assert response.status_code == 403


def test_bad_date_range_is_a_400(db, api, world):
    as_user(world["md"])
    response = api.get("/api/v1/audit/", params={"date_from": "2026-05-02", "date_to": "2026-05-01"})
    assert response.status_code == 400


# ── CSV export ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["gm_a", "am_north"])
def test_csv_export_is_forbidden_for_site_and_area_roles(db, api, world, who):
    _seed_events(db, world)
    as_user(world[who])
    response = api.get("/api/v1/audit/export.csv")
    assert response.status_code == 403


@pytest.mark.parametrize("who", ["md", "rm"])
def test_csv_export_is_allowed_for_senior_roles(db, api, world, who):
    _seed_events(db, world)
    as_user(world[who])
    response = api.get("/api/v1/audit/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment;")

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:4] == ["id", "occurred_at", "actor_user_id", "actor_name"]
    # Same visibility rule as the list endpoint: the unit-less login event is not in the export.
    visible = api.get("/api/v1/audit/", params={"limit": 500}).json()
    assert len(rows) - 1 == len(visible) == 2


def test_csv_export_neutralises_spreadsheet_formulas(db, api, world):
    audit_service.record(
        db, actor=world["md"], entity_type="note", entity_id=1, action="create",
        org_unit_id=world["site_a"].id, summary="=HYPERLINK(\"http://example.test\")",
    )
    db.commit()
    as_user(world["md"])
    rows = list(csv.DictReader(io.StringIO(api.get("/api/v1/audit/export.csv").text)))
    assert rows[0]["summary"] == "'=HYPERLINK(\"http://example.test\")"
