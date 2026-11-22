"""Login and site-scope checks for routes that read or write business data.

Every route in the table below is called three ways:
  * with no token            -> 401
  * as a user of the other site (site B) against a record at site A
                             -> 404, and no row in the database changes
  * as a user of site A      -> the route's existing success response

Runs on an in-memory SQLite engine with the same fixture style as
test_par_and_shopping_list.py. The no-token calls go through the real
get_current_user (no override), so the 401 comes from the app itself.
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token
from app.db.database import Base, get_db
from app.main import app
from app.models import (
    Item, OrgTier, OrgUnit, Supplier, UnitOfMeasure, User, UserRole,
)
from app.models.am_checklist import AMChecklistEntry, AMChecklistTask, ChecklistFrequency
from app.models.approval import ApprovalRule, ApprovalSubject
from app.models.batch import ItemBatch
from app.models.contact import LocationContact
from app.models.cos_flag import CosFlag
from app.models.delivery import Delivery, DeliveryLine
from app.models.item import Department
from app.models.one_on_one import OneOnOneMeeting
from app.models.operational_alert import (
    OpsAlert, OpsAlertType, OpsSeverity, ThresholdConfig, ThresholdDirection,
)
from app.models.ops_visit import OpsVisitReport
from app.models.purchase_order import POStatus, PurchaseOrder, PurchaseOrderLine
from app.models.spot_check import SpotCheckBatchCount, SpotCheckItem, SpotCheckSession
from app.models.stock_count import StockCountLine
from app.services.stock_count_service import create_count, create_template, record_counts


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    """National > North (area) > site A, site B. gm_a, gm_b are site GMs; am_north covers both."""
    uom = UnitOfMeasure(name="each", abbreviation="ea")
    db.add(uom)
    db.flush()
    national = OrgUnit(name="National", tier=OrgTier.NATIONAL)
    db.add(national)
    db.flush()
    north = OrgUnit(name="North", tier=OrgTier.AREA, parent_id=national.id)
    db.add(north)
    db.flush()
    site_a = OrgUnit(name="Site A", tier=OrgTier.SITE, parent_id=north.id)
    site_b = OrgUnit(name="Site B", tier=OrgTier.SITE, parent_id=north.id)
    db.add_all([site_a, site_b])
    db.flush()

    def user(email, name, role, unit):
        u = User(email=email, hashed_password="x", name=name, role=role, org_unit_id=unit.id)
        db.add(u)
        db.flush()
        return u

    gm_a = user("gm.a@example.test", "GM A", UserRole.SITE_GM, site_a)
    gm_b = user("gm.b@example.test", "GM B", UserRole.SITE_GM, site_b)
    am_north = user("am.north@example.test", "AM North", UserRole.AREA_MANAGER, north)

    meat = Supplier(name="Meat Co", code="MEAT")
    db.add(meat)
    db.flush()
    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id,
                 unit_cost=4.50, pack_size=1)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id,
                unit_cost=1.00, pack_size=1)
    db.add_all([steak, salt])
    db.commit()
    return {
        "national": national, "north": north, "site_a": site_a, "site_b": site_b,
        "gm_a": gm_a, "gm_b": gm_b, "am_north": am_north,
        "meat": meat, "steak": steak, "salt": salt,
    }


@pytest.fixture
def seeded(db, world, tmp_path):
    """One record of each kind at site A (plus an empty watch dir for the ingest run)."""
    today = date.today()
    steak, salt, meat = world["steak"], world["salt"], world["meat"]
    site_a, site_b = world["site_a"], world["site_b"]

    po = PurchaseOrder(po_number="PO-SEED-A", supplier_id=meat.id, location_id=site_a.id,
                       status=POStatus.DRAFT, order_date=today, created_by="seed")
    db.add(po)
    db.flush()
    db.add(PurchaseOrderLine(purchase_order_id=po.id, item_id=steak.id,
                             quantity_ordered=2, unit_price=4.5))

    delivery = Delivery(grn_number="GRN-SEED-A", supplier_id=meat.id, location_id=site_a.id,
                        delivery_date=today)
    db.add(delivery)
    db.flush()
    db.add(DeliveryLine(delivery_id=delivery.id, item_id=steak.id, quantity_delivered=1,
                        unit_price=4.5))

    contact = LocationContact(location_id=site_a.id, name="Chef A", email="chef.a@example.test",
                              active_channels="email", departments_subscribed="bar")
    task = AMChecklistTask(frequency=ChecklistFrequency.DAILY, order_num=1,
                           title="Walk the floor", is_active=True)
    db.add_all([contact, task])
    db.flush()
    entry = AMChecklistEntry(task_id=task.id, location_id=site_a.id, period_date=today,
                             completed=True, completed_by="GM A", completed_at=datetime.utcnow())
    visit = OpsVisitReport(location_id=site_a.id, visit_date=today, visit_done_by="AM North",
                           foh={}, boh={}, admin={}, general_property={}, events={})
    meeting = OneOnOneMeeting(location_id=site_a.id, team_member_name="Team A",
                              area_manager_name="AM North", meeting_date=today)
    batch = ItemBatch(item_id=steak.id, location_id=site_a.id, batch_reference="B-A",
                      received_date=today, best_before_date=today + timedelta(days=1),
                      quantity_received=5, quantity_remaining=5)
    flag = CosFlag(org_unit_id=site_a.id, item_id=steak.id, period="2026-11", status="open")
    alert_type = OpsAlertType(key="stock_var", name="Stock variance", source_module="cos")
    db.add_all([entry, visit, meeting, batch, flag, alert_type])
    db.flush()
    alert = OpsAlert(alert_type_id=alert_type.id, org_unit_id=site_a.id,
                     severity=OpsSeverity.HIGH, title="Short on steak")
    threshold = ThresholdConfig(kpi_type="net_sales", org_unit_id=site_a.id, value=100,
                                direction=ThresholdDirection.HIGHER_IS_BETTER)
    db.add_all([alert, threshold])
    db.flush()

    count = create_count(db, org_unit_id=site_a.id, name="Seed count", count_date=today,
                         item_ids=[steak.id], created_by="GM A")
    record_counts(db, count.id, [{"item_id": steak.id, "counted_qty": 3}])
    template = create_template(db, name="Seed template", item_ids=[steak.id], org_unit_id=site_a.id)

    session = SpotCheckSession(location_id=site_a.id, department=Department.KITCHEN,
                               session_date=today, session_slot=1)
    db.add(session)
    db.flush()
    spot_item = SpotCheckItem(session_id=session.id, item_id=steak.id, is_perishable=False,
                              unit_cost=4.5, theoretical_quantity=3)
    spot_item_b = SpotCheckItem(session_id=session.id, item_id=salt.id, is_perishable=True,
                                unit_cost=1.0, theoretical_quantity=5)
    db.add_all([spot_item, spot_item_b])
    db.flush()
    db.add(SpotCheckBatchCount(spot_check_item_id=spot_item_b.id, batch_id=batch.id,
                               expected_quantity=5))

    rule = ApprovalRule(subject=ApprovalSubject.REQUISITION, org_unit_id=site_a.id,
                        min_value=0, levels=["site_gm"], active=True)
    db.add(rule)
    db.commit()

    return {
        **{k: world[k].id for k in ("site_a", "site_b", "meat", "steak", "salt")},
        "po": po.id, "delivery": delivery.id, "contact": contact.id, "task": task.id,
        "entry": entry.id, "visit": visit.id, "meeting": meeting.id, "batch": batch.id,
        "flag": flag.id, "alert": alert.id, "count": count.id, "template": template.id,
        "session": session.id, "spot_item": spot_item.id, "spot_item_b": spot_item_b.id,
        "rule": rule.id, "today": today.isoformat(), "empty_dir": str(tmp_path),
    }


@pytest.fixture
def api(db):
    def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def _snapshot(db) -> dict:
    """Every row of every table, so any write (insert, update or delete) shows up."""
    return {
        table.name: sorted(repr(row) for row in db.execute(table.select()).fetchall())
        for table in Base.metadata.sorted_tables
    }


# ── The route table ───────────────────────────────────────────────────────────
# name -> (method, url, json body, status for an in-scope user, site-scoped?)
# site-scoped routes answer 404 to a user of another site; login-only ones do not.

def cases(s: dict) -> dict:
    a, b, meat, steak, salt = s["site_a"], s["site_b"], s["meat"], s["steak"], s["salt"]
    today = s["today"]
    return {
        # alerts: expiry contacts, trigger, history
        "contacts.list": ("GET", f"/api/v1/alerts/contacts?location_id={a}", None, 200, True),
        "contacts.create": ("POST", "/api/v1/alerts/contacts", {
            "location_id": a, "name": "New", "email": "new@example.test"}, 201, True),
        "contacts.update": ("PATCH", f"/api/v1/alerts/contacts/{s['contact']}", {
            "location_id": a, "name": "Chef A2", "email": "chef.a@example.test"}, 200, True),
        "contacts.deactivate": ("DELETE", f"/api/v1/alerts/contacts/{s['contact']}", None, 204, True),
        "alerts.trigger": ("POST", f"/api/v1/alerts/trigger?location_id={a}", None, 200, True),
        "alerts.history": ("GET", f"/api/v1/alerts/history?location_id={a}", None, 200, True),
        # batches
        "batches.expiring": ("GET", f"/api/v1/batches/expiring?location_id={a}", None, 200, True),
        "batches.active": ("GET", f"/api/v1/batches/active?location_id={a}", None, 200, True),
        # AM checklist
        "am.tasks": ("GET", "/api/v1/am/checklist/tasks", None, 200, False),
        "am.period": ("GET", f"/api/v1/am/checklist/period?location_id={a}&frequency=daily", None, 200, True),
        "am.complete": ("POST", f"/api/v1/am/checklist/tasks/{s['task']}/complete", {
            "location_id": a, "completed_by": "GM A"}, 200, True),
        "am.validate": ("POST", f"/api/v1/am/checklist/entries/{s['entry']}/validate", {
            "validated_by": "AM North"}, 200, True),
        "am.undo": ("POST", f"/api/v1/am/checklist/tasks/{s['task']}/undo?location_id={a}", None, 200, True),
        "am.summary": ("GET", f"/api/v1/am/checklist/summary?location_id={a}", None, 200, True),
        # ops visits
        "ops_visit.list": ("GET", f"/api/v1/am/ops-visits/?location_id={a}", None, 200, True),
        "ops_visit.create": ("POST", "/api/v1/am/ops-visits/", {
            "location_id": a, "visit_date": today, "visit_done_by": "AM North"}, 201, True),
        "ops_visit.get": ("GET", f"/api/v1/am/ops-visits/{s['visit']}", None, 200, True),
        # one-on-ones
        "one_on_one.list": ("GET", f"/api/v1/am/one-on-ones/?location_id={a}", None, 200, True),
        "one_on_one.create": ("POST", "/api/v1/am/one-on-ones/", {
            "location_id": a, "team_member_name": "Team B", "area_manager_name": "AM North",
            "meeting_date": today}, 201, True),
        "one_on_one.get": ("GET", f"/api/v1/am/one-on-ones/{s['meeting']}", None, 200, True),
        # COS and daily pulse
        "cos.variance": ("GET", f"/api/v1/cos/variance?org_unit_id={a}&period=2026-11", None, 200, True),
        "cos.dismiss": ("POST", f"/api/v1/cos/flags/{s['flag']}/dismiss", {"reason": "checked"}, 200, True),
        "daily_pulse": ("GET", f"/api/v1/daily-pulse/?org_unit_id={a}", None, 200, True),
        # deliveries
        "deliveries.list": ("GET", f"/api/v1/deliveries/?location_id={a}", None, 200, True),
        "deliveries.create": ("POST", "/api/v1/deliveries/", {
            "supplier_id": meat, "location_id": a, "delivery_date": today,
            "lines": [{"item_id": steak, "quantity_delivered": 1}]}, 201, True),
        "deliveries.accept": ("POST", f"/api/v1/deliveries/{s['delivery']}/accept?accepted_by=GM%20A",
                              None, 200, True),
        # ingest (login only)
        "ingest.run": ("POST", "/api/v1/ingest/run", {"source": "micros", "watch_dir": s["empty_dir"]},
                       200, False),
        "ingest.recent": ("GET", "/api/v1/ingest/", None, 200, False),
        # operational alerts and thresholds
        "ops_alerts.acknowledge": ("POST", f"/api/v1/ops-alerts/{s['alert']}/acknowledge", None, 200, True),
        "ops_alerts.resolve": ("POST", f"/api/v1/ops-alerts/{s['alert']}/resolve", None, 200, True),
        "ops_alerts.escalate": ("POST", f"/api/v1/ops-alerts/{s['alert']}/escalate", None, 200, True),
        "ops_alerts.dismiss": ("POST", f"/api/v1/ops-alerts/{s['alert']}/dismiss", None, 200, True),
        "ops_alerts.check_escalations": ("POST", "/api/v1/ops-alerts/check-escalations", None, 200, False),
        "ops_alerts.thresholds": ("GET", f"/api/v1/ops-alerts/thresholds?org_unit_id={a}", None, 200, True),
        "ops_alerts.threshold_effective": ("GET", f"/api/v1/ops-alerts/thresholds/effective?kpi_type=net_sales&org_unit_id={a}",
                                           None, 200, True),
        "ops_alerts.threshold_put": ("PUT", "/api/v1/ops-alerts/thresholds", {
            "kpi_type": "net_sales", "org_unit_id": a, "value": 120,
            "direction": "higher_is_better"}, 200, True),
        # org units and users (create only)
        "org_units.create": ("POST", "/api/v1/org-units/", {
            "name": "New site", "tier": "site", "parent_id": a}, 201, True),
        "auth.create_user": ("POST", "/api/v1/auth/users", {
            "email": "new.user@example.test", "password": "pw", "name": "New",
            "role": "site_gm", "org_unit_id": a}, 201, True),
        # waste
        "waste.log": ("POST", "/api/v1/waste/", {
            "org_unit_id": a, "item_id": steak, "quantity": 1, "reason": "spoilage",
            "event_date": today}, 201, True),
        "waste.summary": ("GET", f"/api/v1/waste/summary?org_unit_id={a}&date_from=2026-01-01&date_to=2026-12-31",
                          None, 200, True),
        # stock counts
        "stock_counts.templates_create": ("POST", "/api/v1/stock-counts/templates", {
            "name": "New template", "item_ids": [steak], "org_unit_id": a}, 201, True),
        "stock_counts.templates_list": ("GET", f"/api/v1/stock-counts/templates?org_unit_id={a}", None, 200, True),
        "stock_counts.open": ("POST", "/api/v1/stock-counts/", {
            "org_unit_id": a, "name": "Open count", "item_ids": [steak]}, 201, True),
        "stock_counts.variance_summary": ("GET", f"/api/v1/stock-counts/variance-summary?org_unit_id={a}"
                                          "&date_from=2026-01-01&date_to=2026-12-31", None, 200, True),
        "stock_counts.get": ("GET", f"/api/v1/stock-counts/{s['count']}", None, 200, True),
        "stock_counts.lines": ("PUT", f"/api/v1/stock-counts/{s['count']}/lines", [
            {"item_id": steak, "counted_qty": 4}], 200, True),
        "stock_counts.submit": ("POST", f"/api/v1/stock-counts/{s['count']}/submit", None, 200, True),
        # purchase orders
        "purchase_orders.list": ("GET", f"/api/v1/purchase-orders/?location_id={a}", None, 200, True),
        "purchase_orders.create": ("POST", "/api/v1/purchase-orders/", {
            "supplier_id": meat, "location_id": a, "order_date": today, "created_by": "GM A",
            "lines": [{"item_id": steak, "quantity_ordered": 1, "unit_price": 4.5}]}, 201, True),
        "purchase_orders.get": ("GET", f"/api/v1/purchase-orders/{s['po']}", None, 200, True),
        "purchase_orders.status": ("PATCH", f"/api/v1/purchase-orders/{s['po']}/status?status=sent",
                                   None, 200, True),
        # suppliers (login only: a shared catalogue)
        "suppliers.list": ("GET", "/api/v1/suppliers/", None, 200, False),
        "suppliers.create": ("POST", "/api/v1/suppliers/", {"name": "New Co", "code": "NEW"}, 201, False),
        "suppliers.get": ("GET", f"/api/v1/suppliers/{meat}", None, 200, False),
        "suppliers.items": ("GET", f"/api/v1/suppliers/{meat}/items", None, 200, False),
        "suppliers.add_item": ("POST", f"/api/v1/suppliers/{meat}/items", {
            "item_id": salt, "unit_price": 1.0}, 201, False),
        # spot checks
        "spot_checks.generate": ("POST", "/api/v1/spot-checks/generate", {
            "location_id": a, "department": "general", "session_slot": 2}, 201, True),
        "spot_checks.today": ("GET", f"/api/v1/spot-checks/today?location_id={a}", None, 200, True),
        "spot_checks.get": ("GET", f"/api/v1/spot-checks/{s['session']}", None, 200, True),
        "spot_checks.count": ("POST", f"/api/v1/spot-checks/{s['session']}/items/{s['spot_item']}/count", {
            "actual_quantity": 2, "counted_by": "GM A"}, 200, True),
        "spot_checks.batch_count": ("POST", f"/api/v1/spot-checks/{s['session']}/items/{s['spot_item_b']}/batch-count", {
            "batch_id": s["batch"], "actual_quantity": 4, "counted_by": "GM A"}, 200, True),
        "spot_checks.history": ("GET", f"/api/v1/spot-checks/history/{a}", None, 200, True),
        "spot_checks.coverage": ("GET", f"/api/v1/spot-checks/coverage/{a}/kitchen", None, 200, True),
    }


CASE_NAMES = sorted(cases({
    "site_a": 1, "site_b": 2, "meat": 1, "steak": 1, "salt": 1, "today": "2026-01-01",
    "contact": 1, "task": 1, "entry": 1, "visit": 1, "meeting": 1, "batch": 1, "flag": 1,
    "alert": 1, "count": 1, "template": 1, "session": 1, "spot_item": 1, "spot_item_b": 1,
    "rule": 1, "po": 1, "delivery": 1, "empty_dir": "/nonexistent",
}).keys())


# ── 1. No token -> 401 through the real dependency ────────────────────────────

@pytest.mark.parametrize("name", CASE_NAMES)
def test_no_token_is_401(name, api, seeded):
    method, url, body, _ok, _scoped = cases(seeded)[name]
    res = api.request(method, url, json=body)
    assert res.status_code == 401, (name, res.text)


def test_ocr_extract_without_token_is_401(api):
    res = api.post("/api/v1/invoice-ocr/extract",
                   files={"file": ("invoice.png", b"not-really-a-png", "image/png")})
    assert res.status_code == 401


def test_bad_bearer_token_is_401(api, seeded):
    res = api.get(f"/api/v1/purchase-orders/?location_id={seeded['site_a']}",
                  headers={"Authorization": "Bearer not-a-token"})
    assert res.status_code == 401


def test_real_bearer_token_from_the_app_is_accepted(api, db, world, seeded):
    token = create_access_token(world["gm_a"].id)
    res = api.get(f"/api/v1/purchase-orders/?location_id={seeded['site_a']}",
                  headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert [po["po_number"] for po in res.json()] == ["PO-SEED-A"]


# ── 2. Another site's user -> 404, and nothing changes ────────────────────────

SITE_SCOPED = [name for name, case in cases({
    "site_a": 1, "site_b": 2, "meat": 1, "steak": 1, "salt": 1, "today": "2026-01-01",
    "contact": 1, "task": 1, "entry": 1, "visit": 1, "meeting": 1, "batch": 1, "flag": 1,
    "alert": 1, "count": 1, "template": 1, "session": 1, "spot_item": 1, "spot_item_b": 1,
    "rule": 1, "po": 1, "delivery": 1, "empty_dir": "/nonexistent",
}).items() if case[4]]


@pytest.mark.parametrize("name", SITE_SCOPED)
def test_other_site_user_gets_404_and_nothing_changes(name, api, db, world, seeded):
    method, url, body, _ok, _scoped = cases(seeded)[name]
    before = _snapshot(db)
    as_user(world["gm_b"])
    res = api.request(method, url, json=body)
    assert res.status_code == 404, (name, res.status_code, res.text)
    assert _snapshot(db) == before, name


# ── 3. In-scope user -> the route's existing behaviour ────────────────────────

@pytest.mark.parametrize("name", CASE_NAMES)
def test_in_scope_user_still_works(name, api, world, seeded):
    method, url, body, ok, _scoped = cases(seeded)[name]
    as_user(world["gm_a"])
    res = api.request(method, url, json=body)
    assert res.status_code == ok, (name, res.status_code, res.text)


# ── 4. Body site ids cannot reach into another site's child records ───────────

def test_count_line_write_ignores_body_site_id(api, db, world, seeded):
    """A site B user writes lines to a site A count and puts site A (then site B) in the body."""
    url = f"/api/v1/stock-counts/{seeded['count']}/lines"
    as_user(world["gm_b"])
    for body_site in (seeded["site_a"], seeded["site_b"]):
        res = api.put(url, json=[{"item_id": seeded["steak"], "counted_qty": 9,
                                  "org_unit_id": body_site}])
        assert res.status_code == 404, res.text
    line = db.query(StockCountLine).filter_by(stock_count_id=seeded["count"]).one()
    assert float(line.counted_qty) == 3


def test_purchase_order_status_ignores_body_site_id(api, db, world, seeded):
    as_user(world["gm_b"])
    res = api.patch(f"/api/v1/purchase-orders/{seeded['po']}/status?status=sent",
                    json={"location_id": seeded["site_b"]})
    assert res.status_code == 404
    assert db.get(PurchaseOrder, seeded["po"]).status == POStatus.DRAFT


def test_contact_cannot_be_moved_to_another_site(api, db, world, seeded):
    as_user(world["gm_a"])
    res = api.patch(f"/api/v1/alerts/contacts/{seeded['contact']}", json={
        "location_id": seeded["site_b"], "name": "Moved", "email": "moved@example.test"})
    assert res.status_code == 404
    assert db.get(LocationContact, seeded["contact"]).location_id == seeded["site_a"]


# ── 5. List endpoints without a site only show the caller's subtree ───────────

def test_purchase_order_list_without_site_hides_other_sites(api, world, seeded):
    as_user(world["gm_b"])
    res = api.get("/api/v1/purchase-orders/")
    assert res.status_code == 200
    assert res.json() == []


def test_delivery_and_template_lists_hide_other_sites(api, world, seeded):
    as_user(world["gm_b"])
    assert api.get("/api/v1/deliveries/").json() == []
    assert api.get("/api/v1/stock-counts/templates").json() == []
    as_user(world["gm_a"])
    assert [t["name"] for t in api.get("/api/v1/stock-counts/templates").json()] == ["Seed template"]


def test_threshold_and_rule_lists_hide_other_sites(api, world, seeded):
    as_user(world["gm_b"])
    assert api.get("/api/v1/ops-alerts/thresholds").json() == []
    assert all(r["id"] != seeded["rule"] for r in api.get("/api/v1/approval-rules/").json())
    as_user(world["gm_a"])
    assert any(r["id"] == seeded["rule"] for r in api.get("/api/v1/approval-rules/").json())


def test_alert_trigger_without_site_runs_only_for_own_subtree(api, world, seeded):
    as_user(world["gm_b"])
    res = api.post("/api/v1/alerts/trigger")
    assert res.status_code == 200
    assert res.json()["alerts_sent"] == 0
