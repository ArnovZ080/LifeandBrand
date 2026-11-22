"""Tests for the stock-count screen API: site list, out-of-scope refusal, blind counts.

Runs on an in-memory SQLite engine through the FastAPI test client.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.database import Base, get_db
from app.main import app
from app.models import Item, OrgTier, OrgUnit, UnitOfMeasure, User, UserRole
from app.models.stock import MovementType, StockMovement


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
    """North area with site A and site B. Steak and salt, each with opening stock at site A."""
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
    gm_a = User(email="gm.a@example.test", hashed_password="x", name="GM A",
                role=UserRole.SITE_GM, org_unit_id=site_a.id)
    db.add(gm_a)
    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id,
                 unit_cost=4.50, pack_size=1)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id,
                unit_cost=1.00, pack_size=1)
    db.add_all([steak, salt])
    db.flush()
    db.add_all([
        StockMovement(location_id=site_a.id, item_id=steak.id,
                      movement_type=MovementType.OPENING, quantity=10),
        StockMovement(location_id=site_a.id, item_id=salt.id,
                      movement_type=MovementType.OPENING, quantity=5),
    ])
    db.commit()
    return {"site_a": site_a, "site_b": site_b, "gm_a": gm_a, "steak": steak, "salt": salt}


class _Api:
    """Test client that prefixes paths with the API version."""

    def __init__(self, client):
        self._client = client

    def _url(self, path):
        return f"/api/v1{path}"

    def get(self, path, **kwargs):
        return self._client.get(self._url(path), **kwargs)

    def post(self, path, **kwargs):
        return self._client.post(self._url(path), **kwargs)

    def put(self, path, **kwargs):
        return self._client.put(self._url(path), **kwargs)


@pytest.fixture
def api(db, world):
    def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    app.dependency_overrides[get_current_user] = lambda: world["gm_a"]
    yield _Api(TestClient(app))
    app.dependency_overrides.clear()


def _open_count(api, world, name, blind=None):
    body = {"org_unit_id": world["site_a"].id, "name": name,
            "item_ids": [world["steak"].id, world["salt"].id]}
    if blind is not None:
        body["blind"] = blind
    res = api.post("/stock-counts/", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _line(payload, item):
    return next(line for line in payload["lines"] if line["item_id"] == item.id)


def _submit(api, count_id):
    res = api.post(f"/stock-counts/{count_id}/submit")
    assert res.status_code == 200, res.text
    return res.json()


# ── List ───────────────────────────────────────────────────────────────────────

def test_list_returns_only_the_sites_counts_newest_first_with_progress(api, world):
    first = _open_count(api, world, "Monday")
    second = _open_count(api, world, "Tuesday")
    api.put(f"/stock-counts/{second['id']}/lines",
            json=[{"item_id": world["steak"].id, "counted_qty": 9}])

    res = api.get(f"/stock-counts/?org_unit_id={world['site_a'].id}")
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]]
    assert set(rows[0]) >= {"id", "name", "count_date", "status", "template_id", "line_count", "counted_count"}
    assert rows[0]["line_count"] == 2
    assert rows[0]["counted_count"] == 1
    assert rows[1]["counted_count"] == 0

    open_only = api.get(f"/stock-counts/?org_unit_id={world['site_a'].id}&status=submitted").json()
    assert open_only == []


def test_list_for_an_out_of_scope_site_is_404(api, world):
    _open_count(api, world, "Elsewhere-bound")
    res = api.get(f"/stock-counts/?org_unit_id={world['site_b'].id}")
    assert res.status_code == 404


# ── Blind counts ───────────────────────────────────────────────────────────────

def test_blind_count_hides_system_qty_and_variance_while_open(api, world):
    count = _open_count(api, world, "Blind week", blind=True)
    assert count["blind"] is True

    put = api.put(f"/stock-counts/{count['id']}/lines",
                  json=[{"item_id": world["steak"].id, "counted_qty": 7}])
    assert put.status_code == 200, put.text
    for payload in (count, put.json()):
        for line in payload["lines"]:
            assert line["system_qty"] is None
            assert line["variance_qty"] is None
            assert line["variance_value"] is None
    assert _line(put.json(), world["steak"])["counted_qty"] == 7

    fetched = api.get(f"/stock-counts/{count['id']}").json()
    assert _line(fetched, world["steak"])["system_qty"] is None


def test_blind_count_shows_system_qty_and_variance_after_submit(api, world):
    count = _open_count(api, world, "Blind then done", blind=True)
    api.put(f"/stock-counts/{count['id']}/lines", json=[
        {"item_id": world["steak"].id, "counted_qty": 7},
        {"item_id": world["salt"].id, "counted_qty": 5},
    ])
    submitted = _submit(api, count["id"])
    assert submitted["status"] == "submitted"
    steak = _line(submitted, world["steak"])
    assert steak["system_qty"] == 10
    assert steak["variance_qty"] == -3
    assert steak["variance_value"] == -13.5
    assert _line(submitted, world["salt"])["variance_qty"] == 0

    fetched = api.get(f"/stock-counts/{count['id']}").json()
    assert _line(fetched, world["steak"])["system_qty"] == 10


def test_non_blind_open_count_shows_system_qty_while_open(api, world):
    count = _open_count(api, world, "Open book")
    assert count["blind"] is False
    steak = _line(count, world["steak"])
    assert steak["system_qty"] == 10
    assert steak["variance_qty"] is None  # no variance until a count is recorded and submitted

    api.put(f"/stock-counts/{count['id']}/lines",
            json=[{"item_id": world["steak"].id, "counted_qty": 8}])
    fetched = api.get(f"/stock-counts/{count['id']}").json()
    assert _line(fetched, world["steak"])["system_qty"] == 10
