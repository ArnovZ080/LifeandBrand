"""Tests for per-venue par levels and the shopping list.

Runs on an in-memory SQLite engine. Stock comes from opening StockMovement rows,
which spot_check_selector.get_theoretical_stock sums.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent, Item, OrgTier, OrgUnit, Supplier, SupplierItem, UnitOfMeasure, User, UserRole,
)
from app.models.par_level import ParLevel
from app.models.requisition import Requisition, RequisitionStatus
from app.models.stock import MovementType, StockMovement
from app.services.approval_service import ConflictError
from app.services import requisition_service
from app.services.requisition_service import LineSpec
from app.services.par_service import (
    create_draft_requisitions, delete_par, list_pars, shopping_list, upsert_par,
)


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
    """National > North (area) > site A, site B. Items: steak, lettuce (pack 6), salt (no supplier)."""
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
    veg = Supplier(name="Veg Co", code="VEG")
    db.add_all([meat, veg])
    db.flush()

    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id,
                 unit_cost=4.50, pack_size=1)
    lettuce = Item(code="LET", name="Lettuce", category="veg", unit_of_measure_id=uom.id,
                   unit_cost=1.00, pack_size=6)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id,
                unit_cost=1.00, pack_size=1)
    db.add_all([steak, lettuce, salt])
    db.flush()

    db.add_all([
        SupplierItem(supplier_id=meat.id, item_id=steak.id, unit_price=4.50, pack_size=1, is_preferred=True),
        SupplierItem(supplier_id=veg.id, item_id=lettuce.id, unit_price=1.00, pack_size=6, is_preferred=True),
    ])
    db.commit()
    return {
        "national": national, "north": north, "site_a": site_a, "site_b": site_b,
        "gm_a": gm_a, "gm_b": gm_b, "am_north": am_north,
        "meat": meat, "veg": veg, "steak": steak, "lettuce": lettuce, "salt": salt,
    }


def _stock(db, site, item, qty):
    db.add(StockMovement(location_id=site.id, item_id=item.id,
                         movement_type=MovementType.OPENING, quantity=qty))
    db.commit()


@pytest.fixture
def api(db):
    def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def _line(sl, item):
    for group in sl.groups:
        for line in group.lines:
            if line.item_id == item.id:
                return line
    for line in sl.unassigned:
        if line.item_id == item.id:
            return line
    return None


# ── Par writes ────────────────────────────────────────────────────────────────

def test_reorder_point_not_below_par_is_refused(db, world):
    with pytest.raises(ValueError):
        upsert_par(db, world["site_a"], world["steak"].id, 10, 10, world["gm_a"])
    with pytest.raises(ValueError):
        upsert_par(db, world["site_a"], world["steak"].id, 10, 12, world["gm_a"])


def test_reorder_point_refused_over_the_api_with_400(db, world, api):
    as_user(world["gm_a"])
    res = api.put("/api/v1/par-levels/", json={
        "org_unit_id": world["site_a"].id, "item_id": world["steak"].id,
        "par_qty": 10, "reorder_point": 10,
    })
    assert res.status_code == 400


def test_area_unit_is_refused_for_par_writes(db, world, api):
    with pytest.raises(ValueError):
        upsert_par(db, world["north"], world["steak"].id, 10, 2, world["am_north"])
    as_user(world["am_north"])
    res = api.put("/api/v1/par-levels/", json={
        "org_unit_id": world["north"].id, "item_id": world["steak"].id,
        "par_qty": 10, "reorder_point": 2,
    })
    assert res.status_code == 400
    assert db.execute(select(ParLevel)).scalars().all() == []


# ── Shopping list rules ───────────────────────────────────────────────────────

def test_item_above_reorder_point_is_omitted(db, world):
    _stock(db, world["site_a"], world["steak"], 50)
    upsert_par(db, world["site_a"], world["steak"].id, 20, 10, world["gm_a"])
    sl = shopping_list(db, world["site_a"].id)
    assert sl.groups == []
    assert sl.unassigned == []


def test_at_reorder_point_shortfall_is_par_minus_on_hand(db, world):
    _stock(db, world["site_a"], world["steak"], 4)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 4, world["gm_a"])  # on hand == reorder point
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line is not None
    assert line.on_hand_qty == Decimal("4")
    assert line.order_qty == Decimal("6")


def test_order_quantity_rounds_up_to_pack_size(db, world):
    _stock(db, world["site_a"], world["lettuce"], 3)
    upsert_par(db, world["site_a"], world["lettuce"].id, 10, 5, world["gm_a"])  # shortfall 7, pack 6
    line = _line(shopping_list(db, world["site_a"].id), world["lettuce"])
    assert line.order_qty == Decimal("12")


def test_item_without_preferred_supplier_is_unassigned_and_not_ordered(db, world):
    _stock(db, world["site_a"], world["salt"], 1)
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["salt"].id, 5, 2, world["gm_a"])
    upsert_par(db, world["site_a"], world["steak"].id, 5, 2, world["gm_a"])
    sl = shopping_list(db, world["site_a"].id)
    assert [l.item_id for l in sl.unassigned] == [world["salt"].id]
    assert all(world["salt"].id not in [l.item_id for l in g.lines] for g in sl.groups)

    created = create_draft_requisitions(db, world["site_a"].id, world["gm_a"])
    ordered_items = {l.item_id for r in created for l in r.lines}
    assert world["salt"].id not in ordered_items
    assert world["steak"].id in ordered_items


def test_two_suppliers_produce_two_groups(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    _stock(db, world["site_a"], world["lettuce"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    upsert_par(db, world["site_a"], world["lettuce"].id, 12, 2, world["gm_a"])
    sl = shopping_list(db, world["site_a"].id)
    assert {g.supplier_id for g in sl.groups} == {world["meat"].id, world["veg"].id}


# ── Draft creation ────────────────────────────────────────────────────────────

def test_create_drafts_makes_one_draft_per_supplier_and_never_submits(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    _stock(db, world["site_a"], world["lettuce"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    upsert_par(db, world["site_a"], world["lettuce"].id, 12, 2, world["gm_a"])

    created = create_draft_requisitions(db, world["site_a"].id, world["gm_a"])

    assert len(created) == 2
    assert {r.supplier_id for r in created} == {world["meat"].id, world["veg"].id}
    rows = db.execute(select(Requisition).where(Requisition.org_unit_id == world["site_a"].id)).scalars().all()
    assert len(rows) == 2
    assert all(r.status == RequisitionStatus.DRAFT for r in rows)
    assert all(r.notes == "Created from shopping list" for r in rows)
    assert all(r.requested_by == "GM A" for r in rows)
    events = db.execute(select(AuditEvent).where(AuditEvent.action == "create_drafts")).scalars().all()
    assert len(events) == 1


def test_create_drafts_with_no_orderable_lines_is_409(db, world, api):
    _stock(db, world["site_a"], world["steak"], 50)
    upsert_par(db, world["site_a"], world["steak"].id, 20, 10, world["gm_a"])
    with pytest.raises(ConflictError):
        create_draft_requisitions(db, world["site_a"].id, world["gm_a"])

    as_user(world["gm_a"])
    res = api.post("/api/v1/shopping-list/create-drafts", json={"org_unit_id": world["site_a"].id})
    assert res.status_code == 409
    assert db.execute(select(Requisition)).scalars().all() == []


def test_create_drafts_with_only_unassigned_lines_is_409(db, world):
    _stock(db, world["site_a"], world["salt"], 0)
    upsert_par(db, world["site_a"], world["salt"].id, 5, 2, world["gm_a"])
    with pytest.raises(ConflictError):
        create_draft_requisitions(db, world["site_a"].id, world["gm_a"])


# ── Par lifecycle and audit ───────────────────────────────────────────────────

def test_deactivated_par_no_longer_appears(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    par = upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    assert len(list_pars(db, world["site_a"].id)) == 1
    delete_par(db, par, world["gm_a"])
    assert db.get(ParLevel, par.id).active is False
    assert list_pars(db, world["site_a"].id) == []
    sl = shopping_list(db, world["site_a"].id)
    assert sl.groups == [] and sl.unassigned == []


def test_par_change_writes_audit_row_with_before_and_after(db, world):
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    par = upsert_par(db, world["site_a"], world["steak"].id, 14, 3, world["gm_a"])

    event = db.execute(
        select(AuditEvent).where(AuditEvent.entity_type == "par_level", AuditEvent.action == "update")
    ).scalar_one()
    assert event.org_unit_id == world["site_a"].id
    assert float(event.before["par_qty"]) == 10
    assert float(event.after["par_qty"]) == 14
    assert float(event.before["reorder_point"]) == 2
    assert float(event.after["reorder_point"]) == 3
    assert event.actor_name == "GM A"
    assert event.entity_id == str(par.id)


def test_out_of_scope_user_is_refused_on_another_sites_par_levels(db, world, api):
    par = upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    as_user(world["gm_b"])

    assert api.get(f"/api/v1/par-levels/?org_unit_id={world['site_a'].id}").status_code == 403
    assert api.get(f"/api/v1/shopping-list/?org_unit_id={world['site_a'].id}").status_code == 403
    assert api.post("/api/v1/shopping-list/create-drafts",
                    json={"org_unit_id": world["site_a"].id}).status_code == 403
    assert api.put("/api/v1/par-levels/", json={
        "org_unit_id": world["site_a"].id, "item_id": world["steak"].id,
        "par_qty": 20, "reorder_point": 2,
    }).status_code == 403
    assert api.delete(f"/api/v1/par-levels/{par.id}").status_code == 403
    db.refresh(par)
    assert par.active is True


# ── Stock already on order ────────────────────────────────────────────────────

def _open_draft(db, world, item_key, qty, supplier_key="meat"):
    return requisition_service.create_draft(
        db, org_unit_id=world["site_a"].id,
        lines=[LineSpec(item_id=world[item_key].id, quantity=qty)],
        supplier_id=world[supplier_key].id, notes="test", requested_by="GM A",
        actor=world["gm_a"],
    )


def test_open_draft_requisition_counts_as_on_order(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 8, world["gm_a"])
    _open_draft(db, world, "steak", 6)
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line.on_order_qty == Decimal("6")
    assert line.order_qty == Decimal("4")


def test_stock_position_above_reorder_point_omits_item(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 4, world["gm_a"])
    _open_draft(db, world, "steak", 5)  # position 5 > reorder point 4
    assert _line(shopping_list(db, world["site_a"].id), world["steak"]) is None


def test_approved_requisition_counts_as_on_order(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 8, world["gm_a"])
    req = _open_draft(db, world, "steak", 6)
    requisition_service.submit(db, req, actor=world["gm_a"])  # no rule: approved directly
    assert req.status == RequisitionStatus.APPROVED
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line.on_order_qty == Decimal("6")


def test_rejected_requisition_does_not_count_as_on_order(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    req = _open_draft(db, world, "steak", 6)
    req.status = RequisitionStatus.REJECTED
    db.commit()
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line.on_order_qty == Decimal("0")
    assert line.order_qty == Decimal("10")


def test_converted_requisition_is_not_double_counted_with_its_purchase_order(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 8, world["gm_a"])
    req = _open_draft(db, world, "steak", 3)
    requisition_service.submit(db, req, actor=world["gm_a"])
    requisition_service.convert(db, req, actor=world["gm_a"])
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line.on_order_qty == Decimal("3")


def test_outstanding_part_of_a_sent_purchase_order_counts(db, world):
    from datetime import date
    from app.models.purchase_order import POStatus, PurchaseOrder, PurchaseOrderLine

    _stock(db, world["site_a"], world["steak"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 8, world["gm_a"])
    po = PurchaseOrder(po_number="PO-TEST-OUTSTANDING", supplier_id=world["meat"].id,
                       location_id=world["site_a"].id, status=POStatus.SENT, order_date=date.today())
    po.lines.append(PurchaseOrderLine(item_id=world["steak"].id, quantity_ordered=10,
                                      unit_price=50, quantity_received=3))
    db.add(po)
    db.commit()
    line = _line(shopping_list(db, world["site_a"].id), world["steak"])
    assert line.on_order_qty == Decimal("7")
    assert line.order_qty == Decimal("3")


def test_running_create_drafts_twice_does_not_duplicate_orders(db, world):
    _stock(db, world["site_a"], world["steak"], 0)
    _stock(db, world["site_a"], world["lettuce"], 0)
    upsert_par(db, world["site_a"], world["steak"].id, 10, 2, world["gm_a"])
    upsert_par(db, world["site_a"], world["lettuce"].id, 12, 2, world["gm_a"])

    first = create_draft_requisitions(db, world["site_a"].id, world["gm_a"])
    assert len(first) == 2
    with pytest.raises(ConflictError):
        create_draft_requisitions(db, world["site_a"].id, world["gm_a"])
    rows = db.execute(select(Requisition).where(Requisition.org_unit_id == world["site_a"].id)).scalars().all()
    assert len(rows) == 2

