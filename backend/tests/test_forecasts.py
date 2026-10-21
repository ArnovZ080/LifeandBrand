"""Tests for sales forecasting and predictive ordering (Feature 4).

Runs on an in-memory SQLite engine. Dates that matter to the baseline are fixed
(2026-03-02 is a Monday). Predictive-ordering tests use the real today, because
suggest_order reads sales and stock relative to today.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models import (
    AuditEvent, ForecastLine, ForecastRun, Item, MenuItem, OrgTier, OrgUnit, PurchaseOrder,
    PurchaseOrderLine, RecipeLine, Requisition, Sale, SaleLine, StockCount, StockCountStatus,
    StockMovement, Supplier, SupplierItem, UnitOfMeasure, User, UserRole,
)
from app.models.purchase_order import POStatus
from app.models.requisition import RequisitionStatus
from app.services.forecast_service import (
    METHOD, ForecastError, accuracy, adjust_line, run_forecast,
)
from app.services.predictive_ordering import NotReady, create_draft, suggest_order
from app.services.readiness import is_ready, readiness
from app.services.spot_check_selector import get_theoretical_stock

MONDAY = date(2026, 3, 2)
CHECK_NAMES = ["sales_history", "recent_stock_count", "recipes_cover_sales", "suppliers_linked"]


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
    uom = UnitOfMeasure(name="each", abbreviation="ea")
    db.add(uom)
    db.flush()
    national = OrgUnit(name="National", tier=OrgTier.NATIONAL)
    db.add(national)
    db.flush()
    area = OrgUnit(name="North", tier=OrgTier.AREA, parent_id=national.id)
    db.add(area)
    db.flush()
    site = OrgUnit(name="Site A", tier=OrgTier.SITE, parent_id=area.id)
    db.add(site)
    db.flush()
    gm = User(email="gm.a@example.test", hashed_password="x", name="GM A",
              role=UserRole.SITE_GM, org_unit_id=site.id)
    db.add(gm)

    meat = Supplier(name="Meat Co", code="MEAT")
    veg = Supplier(name="Veg Co", code="VEG")
    db.add_all([meat, veg])
    db.flush()

    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id, unit_cost=4.5)
    lettuce = Item(code="LET", name="Lettuce", category="veg", unit_of_measure_id=uom.id, unit_cost=1.0)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id, unit_cost=0.1)
    db.add_all([steak, lettuce, salt])
    db.flush()

    burger = MenuItem(name="Burger", micros_item_id="B1")
    salad = MenuItem(name="Salad", micros_item_id="S1")
    dessert = MenuItem(name="Dessert", micros_item_id="D1")  # deliberately has no recipe
    db.add_all([burger, salad, dessert])
    db.flush()

    db.add_all([
        RecipeLine(menu_item_id=burger.id, item_id=steak.id, quantity_used=0.25),
        RecipeLine(menu_item_id=salad.id, item_id=lettuce.id, quantity_used=0.2),
    ])
    db.add_all([
        SupplierItem(supplier_id=meat.id, item_id=steak.id, unit_price=4.5, pack_size=5, is_preferred=True),
        SupplierItem(supplier_id=veg.id, item_id=lettuce.id, unit_price=1.0, pack_size=6, is_preferred=True),
    ])
    db.commit()
    return {
        "site": site, "gm": gm, "meat": meat, "veg": veg,
        "steak": steak, "lettuce": lettuce, "salt": salt,
        "burger": burger, "salad": salad, "dessert": dessert,
    }


def _sell(db, site, day, qtys):
    """One Sale for the site on day. qtys maps MenuItem -> quantity."""
    sale = Sale(location_id=site.id, sale_date=day)
    sale.lines = [SaleLine(menu_item_id=menu.id, quantity_sold=qty) for menu, qty in qtys.items()]
    db.add(sale)
    db.flush()
    return sale


def _seed_sales(db, w, days=30):
    """Burger 10 and salad 10 on each of the `days` days before today."""
    today = date.today()
    for offset in range(1, days + 1):
        _sell(db, w["site"], today - timedelta(days=offset), {w["burger"]: 10, w["salad"]: 10})
    db.commit()


def _seed_count(db, w, days_ago=1):
    db.add(StockCount(
        org_unit_id=w["site"].id, name="Weekly count", count_date=date.today() - timedelta(days=days_ago),
        status=StockCountStatus.SUBMITTED, created_by="GM A",
    ))
    db.commit()


def _seed_ready(db, w):
    _seed_sales(db, w)
    _seed_count(db, w)


def _by_item_and_day(run):
    return {(line.business_date, line.menu_item_id): line for line in run.lines}


# ── Forecast baseline and refusal ─────────────────────────────────────────────

def test_baseline_uses_same_weekday_over_trailing_weeks(db, world):
    site, burger, menu_b = world["site"], world["burger"], world["dessert"]
    mondays = [4, 6, 8, 10, 12, 14, 16, 18]  # Monday quantities over the 8 weeks before the start
    for offset in range(56):
        day = MONDAY - timedelta(days=56) + timedelta(days=offset)
        qtys = {burger: mondays[offset // 7] if day.weekday() == 0 else 1}
        if day.weekday() == 4:
            qtys[menu_b] = 5  # the dessert sells only on Fridays
        _sell(db, site, day, qtys)
    db.commit()

    run = run_forecast(db, site.id, MONDAY, horizon_days=7, created_by="GM A")
    lines = _by_item_and_day(run)

    assert run.method == METHOD == "seasonal_baseline_v1"
    assert run.history_days == 56
    assert lines[(MONDAY, burger.id)].baseline_qty == Decimal("11.000")          # mean of the 8 Mondays
    assert lines[(MONDAY + timedelta(days=1), burger.id)].baseline_qty == Decimal("1.000")  # Tuesdays
    assert lines[(MONDAY + timedelta(days=4), menu_b.id)].baseline_qty == Decimal("5.000")  # Fridays


def test_item_with_no_history_on_that_weekday_forecasts_zero(db, world):
    site, burger, dessert = world["site"], world["burger"], world["dessert"]
    for offset in range(1, 57):
        day = MONDAY - timedelta(days=offset)
        qtys = {burger: 3}
        if day.weekday() == 4:
            qtys[dessert] = 5
        _sell(db, site, day, qtys)
    db.commit()

    run = run_forecast(db, site.id, MONDAY, horizon_days=7)
    lines = _by_item_and_day(run)
    assert lines[(MONDAY, dessert.id)].baseline_qty == Decimal("0.000")  # no Monday dessert sales
    assert lines[(MONDAY + timedelta(days=4), dessert.id)].baseline_qty == Decimal("5.000")


def test_run_refused_under_28_sales_days_and_allowed_at_28(db, world):
    site, burger = world["site"], world["burger"]
    for offset in range(1, 28):  # 27 sales days inside the 56-day window
        _sell(db, site, MONDAY - timedelta(days=offset), {burger: 2})
    db.commit()
    with pytest.raises(ForecastError):
        run_forecast(db, site.id, MONDAY)

    _sell(db, site, MONDAY - timedelta(days=28), {burger: 2})  # now 28
    db.commit()
    run = run_forecast(db, site.id, MONDAY)
    assert run.history_days == 28


def test_adjusting_a_line_changes_effective_quantity_and_is_audited(db, world):
    _seed_sales(db, world)
    run = run_forecast(db, world["site"].id, date.today(), horizon_days=3)
    line = run.lines[0]
    baseline = line.baseline_qty

    adjust_line(db, line.id, 7, "Promotion on this day", world["gm"])
    db.refresh(line)
    assert line.effective_qty == Decimal("7")
    assert line.baseline_qty == baseline  # the computed baseline is kept

    event = db.execute(select(AuditEvent).where(
        AuditEvent.entity_type == "forecast_line", AuditEvent.action == "adjust",
        AuditEvent.entity_id == str(line.id),
    )).scalar_one()
    assert event.actor_name == "GM A"
    assert event.after["adjustment_note"] == "Promotion on this day"

    adjust_line(db, line.id, None, None, world["gm"])  # clearing returns to the baseline
    db.refresh(line)
    assert line.effective_qty == baseline


# ── Accuracy ──────────────────────────────────────────────────────────────────

def test_accuracy_is_none_without_overlap(db, world):
    site = world["site"]
    assert accuracy(db, site.id, days=14, as_of=date(2026, 3, 20)) is None  # no sales at all

    _sell(db, site, date(2026, 3, 18), {world["burger"]: 4})
    db.commit()
    assert accuracy(db, site.id, days=14, as_of=date(2026, 3, 20)) is None  # sales but no forecast


def test_accuracy_mape_and_wape_on_hand_checked_example(db, world):
    site, burger, salad = world["site"], world["burger"], world["salad"]
    run = ForecastRun(org_unit_id=site.id, run_date=date(2026, 3, 1), method=METHOD,
                      horizon_days=30, history_days=28)
    db.add(run)
    run.lines.extend([
        ForecastLine(business_date=date(2026, 3, 18), menu_item_id=burger.id, baseline_qty=10),
        ForecastLine(business_date=date(2026, 3, 18), menu_item_id=salad.id, baseline_qty=3),
        ForecastLine(business_date=date(2026, 3, 19), menu_item_id=burger.id, baseline_qty=5),
    ])
    _sell(db, site, date(2026, 3, 18), {burger: 8})   # salad sold 0 that day
    _sell(db, site, date(2026, 3, 19), {burger: 10})
    db.commit()

    result = accuracy(db, site.id, days=14, as_of=date(2026, 3, 20))
    # Item-days: burger 18 (f10, a8), salad 18 (f3, a0), burger 19 (f5, a10).
    # MAPE over actual > 0: (|10-8|/8 + |5-10|/10) / 2 = (0.25 + 0.5) / 2 = 0.375
    # WAPE: (2 + 3 + 5) / (8 + 0 + 10) = 10 / 18
    assert result["item_days"] == 3
    assert result["item_days_with_sales"] == 2
    assert result["days_compared"] == 2
    assert result["mape"] == pytest.approx(0.375)
    assert result["wape"] == pytest.approx(10 / 18)


# ── Readiness gate ────────────────────────────────────────────────────────────

def test_readiness_reports_named_checks(db, world):
    _seed_sales(db, world)  # sales only, no stock count
    checks = readiness(db, world["site"].id, date.today())
    assert [c["name"] for c in checks] == CHECK_NAMES
    by_name = {c["name"]: c for c in checks}
    assert by_name["recent_stock_count"]["passed"] is False
    assert by_name["sales_history"]["passed"] is True
    assert is_ready(checks) is False


def test_sales_history_needs_28_days(db, world):
    site, burger = world["site"], world["burger"]
    for offset in range(1, 28):
        _sell(db, site, date.today() - timedelta(days=offset), {burger: 1})
    db.commit()
    check = {c["name"]: c for c in readiness(db, site.id, date.today())}["sales_history"]
    assert check["passed"] is False


def test_recipe_coverage_check_fails_when_unrecipied_items_dominate(db, world):
    site, dessert = world["site"], world["dessert"]
    _seed_ready(db, world)
    _sell(db, site, date.today() - timedelta(days=2), {dessert: 500})
    db.commit()
    check = {c["name"]: c for c in readiness(db, site.id, date.today())}["recipes_cover_sales"]
    assert check["passed"] is False


# ── Predictive ordering ───────────────────────────────────────────────────────

def test_suggest_refuses_when_not_ready_and_returns_checks(db, world):
    _seed_sales(db, world)
    with pytest.raises(NotReady) as info:
        suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1))
    failing = [c["name"] for c in info.value.checks if not c["passed"]]
    assert failing == ["recent_stock_count"]


def test_override_with_reason_proceeds_and_is_audited(db, world):
    _seed_sales(db, world)  # not ready: no stock count
    suggestion = suggest_order(
        db, world["site"].id, 7, date.today() + timedelta(days=1),
        override=True, override_reason="Count delayed, GM confirmed stock on hand",
        actor=world["gm"],
    )
    assert suggestion.overridden is True
    assert suggestion.lines  # a suggestion was produced
    event = db.execute(select(AuditEvent).where(
        AuditEvent.entity_type == "predictive_order", AuditEvent.action == "override",
    )).scalar_one()
    assert event.after["reason"] == "Count delayed, GM confirmed stock on hand"
    assert [c["name"] for c in event.after["failing_checks"]] == ["recent_stock_count"]


def test_override_without_reason_is_refused(db, world):
    _seed_sales(db, world)
    with pytest.raises(ValueError):
        suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1), override=True)
    with pytest.raises(ValueError):
        suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1),
                      override=True, override_reason="   ")


def test_pack_rounding_and_stock_override_without_movements(db, world):
    _seed_ready(db, world)
    site, steak, lettuce = world["site"], world["steak"], world["lettuce"]
    delivery = date.today() + timedelta(days=1)

    suggestion = suggest_order(db, site.id, 7, delivery)
    lines = {line.item_id: line for line in suggestion.lines}
    # Eight business dates (today through today+7): steak 8 x 10 x 0.25 = 20, pack 5.
    assert lines[steak.id].required_qty == Decimal("20.000")
    assert lines[steak.id].suggested_qty == Decimal("20.0000")
    # Lettuce 8 x 10 x 0.2 = 16, pack 6, rounds up to 18.
    assert lines[lettuce.id].suggested_qty == Decimal("18.0000")
    assert lines[lettuce.id].supplier_id == world["veg"].id

    movements_before = db.execute(select(func.count(StockMovement.id))).scalar()
    overridden = suggest_order(db, site.id, 7, delivery, stock_overrides={steak.id: 12.5})
    movements_after = db.execute(select(func.count(StockMovement.id))).scalar()
    assert movements_after == movements_before  # overrides write no stock movement
    assert get_theoretical_stock(db, site.id, steak.id) == 0.0

    steak_line = {line.item_id: line for line in overridden.lines}[steak.id]
    assert steak_line.on_hand_qty == Decimal("12.5000")
    assert steak_line.suggested_qty == Decimal("10.0000")  # need 7.5 rounds up to 2 packs of 5
    assert overridden.stock_overrides_applied == [steak.id]


def test_items_without_a_supplier_are_listed_unassigned(db, world):
    _seed_sales(db, world)  # no count, so override is needed
    db.add(RecipeLine(menu_item_id=world["salad"].id, item_id=world["salt"].id, quantity_used=0.01))
    db.commit()
    suggestion = suggest_order(
        db, world["site"].id, 7, date.today() + timedelta(days=1),
        override=True, override_reason="Testing unassigned items",
    )
    unassigned = {u.item_id: u for u in suggestion.unassigned}
    assert world["salt"].id in unassigned
    assert unassigned[world["salt"].id].reason == "no preferred supplier"
    assert world["salt"].id not in {line.item_id for line in suggestion.lines}


def test_supplier_filter_limits_lines_to_that_supplier(db, world):
    _seed_ready(db, world)
    suggestion = suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1),
                               supplier_id=world["veg"].id)
    assert {line.supplier_id for line in suggestion.lines} == {world["veg"].id}
    unassigned = {u.item_id: u.reason for u in suggestion.unassigned}
    assert unassigned[world["steak"].id] == "not supplied by the selected supplier"


def test_last_order_and_four_week_average_come_from_purchase_history(db, world):
    _seed_ready(db, world)
    site, steak, meat = world["site"], world["steak"], world["meat"]
    today = date.today()
    for order_date, qty in [(today - timedelta(days=20), 10), (today - timedelta(days=3), 15)]:
        po = PurchaseOrder(po_number=f"PO-T-{order_date:%Y%m%d}", supplier_id=meat.id,
                           location_id=site.id, status=POStatus.SENT, order_date=order_date)
        po.lines.append(PurchaseOrderLine(item_id=steak.id, quantity_ordered=qty,
                                          unit_price=4.5, quantity_received=0))
        db.add(po)
    db.commit()

    line = {l.item_id: l for l in suggest_order(db, site.id, 7, today + timedelta(days=1)).lines}[steak.id]
    assert line.last_order_qty == Decimal("15")
    assert line.four_week_avg_order_qty == Decimal("12.5")


def test_create_drafts_one_per_supplier_and_never_submitted(db, world):
    _seed_ready(db, world)
    suggestion = suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1))
    assert {line.supplier_id for line in suggestion.lines} == {world["meat"].id, world["veg"].id}

    requisitions = create_draft(db, suggestion, requested_by="GM A", actor=world["gm"])

    assert len(requisitions) == 2
    assert {r.supplier_id for r in requisitions} == {world["meat"].id, world["veg"].id}
    for requisition in requisitions:
        db.refresh(requisition)
        assert requisition.status == RequisitionStatus.DRAFT
        assert requisition.submitted_at is None
        assert requisition.notes == f"Suggested by forecast run {suggestion.forecast_run_id}"
    assert db.execute(select(func.count(Requisition.id)).where(
        Requisition.status == RequisitionStatus.SUBMITTED)).scalar() == 0
    drafts_event = db.execute(select(AuditEvent).where(AuditEvent.action == "create_drafts")).scalar_one()
    assert len(drafts_event.after["requisitions"]) == 2


def test_create_drafts_refused_when_not_ready(db, world):
    _seed_sales(db, world)
    with pytest.raises(NotReady):
        suggest_order(db, world["site"].id, 7, date.today() + timedelta(days=1))


# ── HTTP layer ────────────────────────────────────────────────────────────────

@pytest.fixture
def api(db, world):
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.db.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: world["gm"]
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_http_suggest_is_409_with_checks_when_not_ready(api, db, world):
    _seed_sales(db, world)
    response = api.post("/api/v1/predictive-orders/suggest", json={
        "org_unit_id": world["site"].id, "coverage_days": 7,
        "delivery_date": (date.today() + timedelta(days=1)).isoformat(),
    })
    assert response.status_code == 409
    checks = response.json()["detail"]["checks"]
    assert [c["name"] for c in checks if not c["passed"]] == ["recent_stock_count"]


def test_http_suggest_with_string_keyed_overrides_and_create_drafts(api, db, world):
    _seed_ready(db, world)
    body = {
        "org_unit_id": world["site"].id, "coverage_days": 7,
        "delivery_date": (date.today() + timedelta(days=1)).isoformat(),
        "stock_overrides": {str(world["steak"].id): 12.5},  # JSON object keys are strings
    }
    response = api.post("/api/v1/predictive-orders/suggest", json=body)
    assert response.status_code == 200
    lines = {line["item_id"]: line for line in response.json()["lines"]}
    assert lines[world["steak"].id]["suggested_qty"] == 10.0

    response = api.post("/api/v1/predictive-orders/suggest/create-drafts", json=body)
    assert response.status_code == 201
    created = response.json()["requisitions"]
    assert len(created) == 2
    assert {r["status"] for r in created} == {"DRAFT"}


def test_http_outside_scope_is_403_and_bad_override_is_400(api, db, world):
    _seed_ready(db, world)
    other = OrgUnit(name="Elsewhere", tier=OrgTier.SITE, parent_id=None)
    db.add(other)
    db.commit()
    response = api.post("/api/v1/predictive-orders/suggest", json={
        "org_unit_id": other.id, "coverage_days": 7,
        "delivery_date": date.today().isoformat(),
    })
    assert response.status_code == 403

    response = api.post("/api/v1/predictive-orders/suggest", json={
        "org_unit_id": world["site"].id, "coverage_days": 7,
        "delivery_date": date.today().isoformat(), "override": True,
    })
    assert response.status_code == 400  # override without a reason


def test_http_forecast_run_and_adjust_line(api, db, world):
    _seed_sales(db, world)
    response = api.post("/api/v1/forecasts/runs", json={
        "org_unit_id": world["site"].id, "start_date": date.today().isoformat(), "horizon_days": 2,
    })
    assert response.status_code == 201
    run = response.json()
    line = run["lines"][0]
    assert line["effective_qty"] == line["baseline_qty"]

    response = api.patch(f"/api/v1/forecasts/lines/{line['id']}", json={
        "adjusted_qty": 4, "adjustment_note": "Event",
    })
    assert response.status_code == 200
    assert response.json()["effective_qty"] == 4.0

    response = api.get(f"/api/v1/forecasts/readiness?org_unit_id={world['site'].id}")
    assert response.status_code == 200
    assert response.json()["ready"] is False
