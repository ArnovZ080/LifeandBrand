"""Tests for requisitions and multi-level approvals (Feature 2).

Runs on an in-memory SQLite engine. Nothing here is Postgres-only: enums, JSON
levels and the recursive subtree CTE all work on SQLite. The enum types and the
migration are Postgres-specific and are checked separately (see the report).
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.database import Base, get_db
from app.models import (
    Item, OrgTier, OrgUnit, Supplier, SupplierItem, UnitOfMeasure, User, UserRole,
    VendorPriceCatalogue,
)
from app.models.approval import (
    ApprovalStatus, ApprovalSubject, DecisionOutcome,
)
from app.models.purchase_order import POStatus
from app.models.requisition import RequisitionStatus
from app.services import approval_service
from app.services.approval_service import (
    ConflictError, create_rule, decide, find_rule, get_request, open_request,
)
from app.services.requisition_service import (
    LineSpec, convert, create_draft, submit, update_draft,
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
    """National > (North: site A, site B) and (South: site C).

    Items: steak (4.50, preferred meat supplier), wine (12.00, preferred wine
    supplier), salt (1.00, no preferred supplier). Users sit at different levels.
    """
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
    site_b = OrgUnit(name="Site B", tier=OrgTier.SITE, parent_id=north.id)
    site_c = OrgUnit(name="Site C", tier=OrgTier.SITE, parent_id=south.id)
    db.add_all([site_a, site_b, site_c])
    db.flush()

    def user(email, name, role, unit):
        u = User(email=email, hashed_password="x", name=name, role=role, org_unit_id=unit.id)
        db.add(u)
        db.flush()
        return u

    users = {
        "gm_a": user("gm.a@example.test", "GM A", UserRole.SITE_GM, site_a),
        "am_north": user("am.north@example.test", "AM North", UserRole.AREA_MANAGER, north),
        "am_south": user("am.south@example.test", "AM South", UserRole.AREA_MANAGER, south),
        "rm": user("rm@example.test", "RM", UserRole.REGIONAL_MANAGER, national),
        "md": user("md@example.test", "MD", UserRole.MD, national),
    }

    meat = Supplier(name="Meat Co", code="MEAT")
    wine_co = Supplier(name="Wine Co", code="WINE")
    db.add_all([meat, wine_co])
    db.flush()

    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id, unit_cost=4.50)
    wine = Item(code="WNE", name="House red", category="bar", unit_of_measure_id=uom.id, unit_cost=12.00)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id, unit_cost=1.00)
    truffle = Item(code="TRF", name="Truffle", category="dry", unit_of_measure_id=uom.id, unit_cost=None)
    db.add_all([steak, wine, salt, truffle])
    db.flush()

    db.add_all([
        SupplierItem(supplier_id=meat.id, item_id=steak.id, unit_price=4.50, is_preferred=True),
        SupplierItem(supplier_id=wine_co.id, item_id=wine.id, unit_price=12.00, is_preferred=True),
    ])
    db.commit()
    return {
        "national": national, "north": north, "south": south,
        "site_a": site_a, "site_b": site_b, "site_c": site_c,
        "meat": meat, "wine_co": wine_co,
        "steak": steak, "wine": wine, "salt": salt, "truffle": truffle,
        **users,
    }


def _lines(*pairs):
    return [LineSpec(item_id=item.id, quantity=qty) for item, qty in pairs]


def _draft(db, w, unit, lines, **kwargs):
    return create_draft(db, org_unit_id=unit.id, lines=lines, requested_by="GM A", **kwargs)


def _two_level_rule(db, national):
    return create_rule(
        db, subject=ApprovalSubject.REQUISITION, org_unit_id=None, min_value=0,
        max_value=None, levels=["area_manager", "regional_manager"],
    )


# ── Approval engine ───────────────────────────────────────────────────────────

def test_submit_without_matching_rule_approves_directly(db, world):
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 2)))

    submit(db, req, today=date(2026, 10, 21))

    assert req.status == RequisitionStatus.APPROVED
    assert float(req.total_value) == pytest.approx(9.00)
    assert float(req.lines[0].unit_price) == pytest.approx(4.50)
    assert get_request(db, ApprovalSubject.REQUISITION, req.id) is None


def test_unit_price_prefers_unit_catalogue_then_tenant_then_unit_cost(db, world):
    site_a = world["site_a"]
    db.add_all([
        # steak: a site price beats the tenant-wide price
        VendorPriceCatalogue(item_id=world["steak"].id, supplier_id=world["meat"].id,
                             org_unit_id=site_a.id, price=3.90, unit="kg", valid_from=date(2000, 1, 1)),
        VendorPriceCatalogue(item_id=world["steak"].id, supplier_id=world["meat"].id,
                             org_unit_id=None, price=4.10, unit="kg", valid_from=date(2000, 1, 1)),
        # wine: tenant-wide price beats item.unit_cost
        VendorPriceCatalogue(item_id=world["wine"].id, supplier_id=world["wine_co"].id,
                             org_unit_id=None, price=11.50, unit="btl", valid_from=date(2000, 1, 1)),
        # salt: a future-dated price is ignored, so unit_cost applies
        VendorPriceCatalogue(item_id=world["salt"].id, supplier_id=world["meat"].id,
                             org_unit_id=None, price=0.80, unit="kg", valid_from=date(2999, 1, 1)),
    ])
    db.commit()
    req = _draft(db, world, site_a, _lines((world["steak"], 1), (world["wine"], 1), (world["salt"], 1)))

    submit(db, req, today=date(2026, 10, 21))

    prices = {line.item_id: float(line.unit_price) for line in req.lines}
    assert prices[world["steak"].id] == pytest.approx(3.90)
    assert prices[world["wine"].id] == pytest.approx(11.50)
    assert prices[world["salt"].id] == pytest.approx(1.00)
    assert float(req.total_value) == pytest.approx(3.90 + 11.50 + 1.00)


def test_submit_refuses_item_with_no_price_and_leaves_draft_untouched(db, world):
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 1), (world["truffle"], 1)))

    with pytest.raises(ValueError, match="No price"):
        submit(db, req)

    db.refresh(req)
    assert req.status == RequisitionStatus.DRAFT
    assert all(line.unit_price is None for line in req.lines)


def test_two_level_rule_needs_both_approvals_in_order(db, world):
    _two_level_rule(db, world["national"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 2)))
    submit(db, req)
    assert req.status == RequisitionStatus.SUBMITTED

    request = get_request(db, ApprovalSubject.REQUISITION, req.id)
    assert request.status == ApprovalStatus.PENDING
    assert request.current_level == 1
    assert list(request.levels) == ["area_manager", "regional_manager"]

    decide(db, request, world["am_north"], DecisionOutcome.APPROVED, "looks right")
    assert request.current_level == 2
    assert req.status == RequisitionStatus.SUBMITTED

    decide(db, request, world["rm"], DecisionOutcome.APPROVED)
    assert request.status == ApprovalStatus.APPROVED
    assert request.closed_at is not None
    assert req.status == RequisitionStatus.APPROVED
    assert [(d.level, d.approver_role) for d in request.decisions] == [
        (1, "area_manager"), (2, "regional_manager"),
    ]

    with pytest.raises(ConflictError):
        decide(db, request, world["rm"], DecisionOutcome.APPROVED)


def test_wrong_role_decision_is_refused(db, world):
    _two_level_rule(db, world["national"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 2)))
    submit(db, req)
    request = get_request(db, ApprovalSubject.REQUISITION, req.id)

    # The site GM is in scope but is not the level-1 role.
    with pytest.raises(PermissionError, match="requires role 'area_manager'"):
        decide(db, request, world["gm_a"], DecisionOutcome.APPROVED)

    # The regional manager has the level-2 role, but level 1 is still pending.
    with pytest.raises(PermissionError):
        decide(db, request, world["rm"], DecisionOutcome.APPROVED)

    assert request.current_level == 1
    assert request.decisions == []


def test_out_of_scope_approver_is_refused(db, world):
    _two_level_rule(db, world["national"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 2)))
    submit(db, req)
    request = get_request(db, ApprovalSubject.REQUISITION, req.id)

    # Right role (area_manager) but the South area does not cover Site A.
    with pytest.raises(PermissionError, match="does not cover"):
        decide(db, request, world["am_south"], DecisionOutcome.APPROVED)

    assert request.current_level == 1
    assert request.decisions == []


def test_rejection_closes_request_and_requisition(db, world):
    _two_level_rule(db, world["national"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 2)))
    submit(db, req)
    request = get_request(db, ApprovalSubject.REQUISITION, req.id)

    decide(db, request, world["am_north"], DecisionOutcome.REJECTED, "too expensive")

    assert request.status == ApprovalStatus.REJECTED
    assert request.closed_at is not None
    assert req.status == RequisitionStatus.REJECTED
    with pytest.raises(ConflictError):
        decide(db, request, world["rm"], DecisionOutcome.APPROVED)
    with pytest.raises(ConflictError):
        convert(db, req)


def test_most_specific_rule_wins_and_global_is_the_fallback(db, world):
    create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None, min_value=0,
                max_value=None, levels=["regional_manager"])
    create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=world["north"].id,
                min_value=0, max_value=1000, levels=["area_manager"])

    # Site A is under North: the North rule (more specific) applies.
    rule = find_rule(db, ApprovalSubject.REQUISITION, world["site_a"].id, 9)
    assert rule.org_unit_id == world["north"].id

    # Site C is under South: only the global rule matches.
    rule = find_rule(db, ApprovalSubject.REQUISITION, world["site_c"].id, 9)
    assert rule.org_unit_id is None

    # Above the North rule's ceiling, the global rule applies even at Site A.
    rule = find_rule(db, ApprovalSubject.REQUISITION, world["site_a"].id, 1000)
    assert rule.org_unit_id is None


def test_open_request_copies_levels_so_later_rule_edits_do_not_change_it(db, world):
    rule = _two_level_rule(db, world["national"])
    request = open_request(db, ApprovalSubject.REQUISITION, 999, world["site_a"].id, 100)
    assert list(request.levels) == ["area_manager", "regional_manager"]

    rule.levels = ["md"]
    db.commit()
    db.refresh(request)
    assert list(request.levels) == ["area_manager", "regional_manager"]


# ── Conversion to purchase orders ─────────────────────────────────────────────

def test_convert_splits_lines_into_one_po_per_supplier(db, world):
    req = _draft(db, world, world["site_a"],
                 _lines((world["steak"], 2), (world["wine"], 1), (world["salt"], 3)),
                 supplier_id=world["meat"].id)
    submit(db, req)
    assert req.status == RequisitionStatus.APPROVED

    pos = convert(db, req, today=date(2026, 10, 21))

    assert req.status == RequisitionStatus.CONVERTED
    assert len(pos) == 2
    by_supplier = {po.supplier_id: po for po in pos}
    assert set(by_supplier) == {world["meat"].id, world["wine_co"].id}

    meat_po = by_supplier[world["meat"].id]
    wine_po = by_supplier[world["wine_co"].id]
    assert sorted(line.item_id for line in meat_po.lines) == sorted([world["steak"].id, world["salt"].id])
    assert [line.item_id for line in wine_po.lines] == [world["wine"].id]
    assert all(po.status == POStatus.DRAFT for po in pos)
    assert all(po.location_id == world["site_a"].id for po in pos)
    assert {po.po_number for po in pos} == {"PO-20261021-0001", "PO-20261021-0002"}

    steak_line = next(line for line in meat_po.lines if line.item_id == world["steak"].id)
    assert float(steak_line.unit_price) == pytest.approx(4.50)
    assert steak_line.supplier_item_id is not None
    salt_line = next(line for line in meat_po.lines if line.item_id == world["salt"].id)
    assert salt_line.supplier_item_id is None  # no SupplierItem for salt at the meat supplier


def test_convert_refused_unless_approved(db, world):
    draft = _draft(db, world, world["site_a"], _lines((world["steak"], 1)))
    with pytest.raises(ConflictError):
        convert(db, draft)

    _two_level_rule(db, world["national"])
    pending = _draft(db, world, world["site_a"], _lines((world["steak"], 1)))
    submit(db, pending)
    assert pending.status == RequisitionStatus.SUBMITTED
    with pytest.raises(ConflictError):
        convert(db, pending)


def test_convert_refuses_line_with_no_supplier(db, world):
    req = _draft(db, world, world["site_a"], _lines((world["salt"], 1)))  # no preferred, no requisition supplier
    submit(db, req)

    with pytest.raises(ValueError, match="No supplier for item SLT"):
        convert(db, req)
    assert req.status == RequisitionStatus.APPROVED


def test_po_over_threshold_opens_po_approval_and_approval_keeps_po_in_draft(db, world):
    create_rule(db, subject=ApprovalSubject.PURCHASE_ORDER, org_unit_id=None, min_value=500,
                max_value=None, levels=["area_manager"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 150), (world["wine"], 10)))
    submit(db, req)  # no REQUISITION rule: approved directly
    assert req.status == RequisitionStatus.APPROVED

    pos = convert(db, req)
    big = next(po for po in pos if po.supplier_id == world["meat"].id)  # 150 x 4.50 = 675
    small = next(po for po in pos if po.supplier_id == world["wine_co"].id)  # 10 x 12.00 = 120

    big_request = get_request(db, ApprovalSubject.PURCHASE_ORDER, big.id)
    assert big_request is not None and big_request.status == ApprovalStatus.PENDING
    assert get_request(db, ApprovalSubject.PURCHASE_ORDER, small.id) is None

    decide(db, big_request, world["am_north"], DecisionOutcome.APPROVED)
    db.refresh(big)
    assert big_request.status == ApprovalStatus.APPROVED
    assert big.status == POStatus.DRAFT  # the buyer still sends it


def test_rejected_po_approval_cancels_the_purchase_order(db, world):
    create_rule(db, subject=ApprovalSubject.PURCHASE_ORDER, org_unit_id=None, min_value=500,
                max_value=None, levels=["area_manager"])
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 150)))
    submit(db, req)
    (po,) = convert(db, req)

    request = get_request(db, ApprovalSubject.PURCHASE_ORDER, po.id)
    decide(db, request, world["am_north"], DecisionOutcome.REJECTED, "over budget")

    db.refresh(po)
    assert request.status == ApprovalStatus.REJECTED
    assert po.status == POStatus.CANCELLED


# ── Drafts and rules ──────────────────────────────────────────────────────────

def test_draft_can_be_edited_until_submitted_then_is_frozen(db, world):
    req = _draft(db, world, world["site_a"], _lines((world["steak"], 1)))

    update_draft(db, req, _lines((world["steak"], 2), (world["wine"], 1)),
                 supplier_id=None, needed_by=None, notes="weekend")
    assert sorted(line.item_id for line in req.lines) == sorted([world["steak"].id, world["wine"].id])

    submit(db, req)
    with pytest.raises(ConflictError):
        update_draft(db, req, _lines((world["steak"], 5)),
                     supplier_id=None, needed_by=None, notes=None)
    db.refresh(req)
    assert req.status == RequisitionStatus.APPROVED
    assert len(req.lines) == 2


def test_rule_validation_rejects_six_levels_and_invalid_role(db, world):
    with pytest.raises(ValueError, match="1 to 5"):
        create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None,
                    levels=["area_manager"] * 6)
    with pytest.raises(ValueError, match="Invalid role"):
        create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None,
                    levels=["area_manager", "wizard"])
    with pytest.raises(ValueError, match="1 to 5"):
        create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None, levels=[])

    # Five levels, all valid, is accepted.
    rule = create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None,
                       levels=["site_gm", "area_manager", "regional_manager", "national_ops", "md"])
    assert len(rule.levels) == 5


def test_overlapping_active_rules_for_same_unit_are_refused(db, world):
    north = world["north"].id
    create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=north,
                min_value=0, max_value=1000, levels=["area_manager"])

    with pytest.raises(ConflictError):
        create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=north,
                    min_value=500, max_value=2000, levels=["area_manager"])
    # Touching ranges [0,1000) and [1000,2000) do not overlap.
    create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=north,
                min_value=1000, max_value=2000, levels=["regional_manager"])
    # A different unit or subject is not an overlap.
    create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=world["south"].id,
                min_value=0, max_value=1000, levels=["area_manager"])
    create_rule(db, subject=ApprovalSubject.PURCHASE_ORDER, org_unit_id=north,
                min_value=0, max_value=1000, levels=["area_manager"])


def test_update_rule_can_deactivate_and_reactivate(db, world):
    rule = create_rule(db, subject=ApprovalSubject.REQUISITION, org_unit_id=None,
                       levels=["area_manager"])
    approval_service.update_rule(db, rule, {"active": False})
    assert find_rule(db, ApprovalSubject.REQUISITION, world["site_a"].id, 10) is None
    approval_service.update_rule(db, rule, {"active": True, "levels": ["regional_manager"]})
    assert list(rule.levels) == ["regional_manager"]


# ── HTTP layer ────────────────────────────────────────────────────────────────

@pytest.fixture
def api(db, world):
    """TestClient bound to the test session; call as_user(key) to switch caller."""
    from app.main import app

    state = {"user": world["md"]}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]

    class Api:
        client = TestClient(app)

        def as_user(self, key):
            state["user"] = world[key]
            return self

        def __getattr__(self, name):
            return getattr(self.client, name)

    yield Api()
    app.dependency_overrides.clear()


def test_http_status_codes_for_requisition_flow(api, db, world):
    # Creating for a unit outside the caller's subtree is 403.
    body = {"org_unit_id": world["site_c"].id, "requested_by": "GM A",
            "lines": [{"item_id": world["steak"].id, "quantity": 1}]}
    assert api.as_user("gm_a").post("/api/v1/requisitions/", json=body).status_code == 403

    created = api.as_user("gm_a").post("/api/v1/requisitions/", json={
        "org_unit_id": world["site_a"].id, "requested_by": "GM A",
        "lines": [{"item_id": world["steak"].id, "quantity": 2}],
    })
    assert created.status_code == 201
    req_id = created.json()["id"]

    # Another site's GM cannot see it.
    assert api.as_user("am_south").get(f"/api/v1/requisitions/{req_id}").status_code == 404
    assert api.as_user("gm_a").get(f"/api/v1/requisitions/{req_id}").status_code == 200

    assert api.as_user("gm_a").get("/api/v1/requisitions/999999").status_code == 404

    assert api.as_user("gm_a").post(f"/api/v1/requisitions/{req_id}/submit").status_code == 200
    # Editing after submit is a conflict.
    edit = api.as_user("gm_a").put(f"/api/v1/requisitions/{req_id}", json={
        "lines": [{"item_id": world["steak"].id, "quantity": 9}],
    })
    assert edit.status_code == 409
    # Converting is allowed (no rule, so approved) and produces a PO.
    converted = api.as_user("gm_a").post(f"/api/v1/requisitions/{req_id}/convert")
    assert converted.status_code == 200
    assert converted.json()["requisition"]["status"] == "CONVERTED"
    assert len(converted.json()["purchase_orders"]) == 1


def test_http_decision_and_rule_errors(api, db, world):
    # Rule creation by a site GM is refused; a six-level rule is a 400 for the MD.
    rule_body = {"subject": "REQUISITION", "org_unit_id": None, "levels": ["area_manager"]}
    assert api.as_user("gm_a").post("/api/v1/approval-rules/", json=rule_body).status_code == 403
    too_long = {**rule_body, "levels": ["area_manager"] * 6}
    assert api.as_user("md").post("/api/v1/approval-rules/", json=too_long).status_code == 400
    bad_role = {**rule_body, "levels": ["wizard"]}
    assert api.as_user("md").post("/api/v1/approval-rules/", json=bad_role).status_code == 400
    assert api.as_user("md").post("/api/v1/approval-rules/", json=rule_body).status_code == 201
    # The global rule now exists; a second global rule with the same range overlaps.
    assert api.as_user("md").post("/api/v1/approval-rules/", json=rule_body).status_code == 409

    # Decisions: out-of-scope approver is 403; decision without an open approval is 404.
    created = api.as_user("gm_a").post("/api/v1/requisitions/", json={
        "org_unit_id": world["site_a"].id, "requested_by": "GM A",
        "lines": [{"item_id": world["steak"].id, "quantity": 2}],
    }).json()
    api.as_user("gm_a").post(f"/api/v1/requisitions/{created['id']}/submit")
    # Requisition is SUBMITTED under the global rule (levels: area_manager only).
    decision = api.as_user("am_south").post(
        f"/api/v1/requisitions/{created['id']}/decisions", json={"decision": "approved"})
    assert decision.status_code == 403
    ok = api.as_user("am_north").post(
        f"/api/v1/requisitions/{created['id']}/decisions", json={"decision": "approved"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "APPROVED"
    assert api.as_user("am_north").post(
        f"/api/v1/requisitions/{created['id']}/decisions", json={"decision": "approved"}
    ).status_code == 409

    no_approval = api.as_user("am_north").post("/api/v1/requisitions/", json={
        "org_unit_id": world["site_b"].id, "requested_by": "GM B",
        "lines": [{"item_id": world["salt"].id, "quantity": 1}],
    }).json()
    assert api.as_user("md").post(
        f"/api/v1/requisitions/{no_approval['id']}/decisions", json={"decision": "rejected"}
    ).status_code == 404


def test_http_decision_is_committed_and_survives_rollback(api, db, world):
    from app.models.approval import ApprovalDecision

    api.as_user("md").post("/api/v1/approval-rules/", json={
        "subject": "REQUISITION", "org_unit_id": None, "levels": ["area_manager"],
    })
    created = api.as_user("gm_a").post("/api/v1/requisitions/", json={
        "org_unit_id": world["site_a"].id, "requested_by": "GM A",
        "lines": [{"item_id": world["steak"].id, "quantity": 2}],
    }).json()
    api.as_user("gm_a").post(f"/api/v1/requisitions/{created['id']}/submit")
    ok = api.as_user("am_north").post(
        f"/api/v1/requisitions/{created['id']}/decisions", json={"decision": "approved"})
    assert ok.status_code == 200

    db.rollback()
    assert db.query(ApprovalDecision).count() == 1
