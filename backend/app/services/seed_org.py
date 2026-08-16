"""
Idempotent org-structure seeding for the Life & Brand portfolio (Phase 0).

Ensures the tenant, the three brands, the Cape Town area and its six sites
exist. Matches on tenant/brand name and org unit pos_site_code, so it is
safe to call on every startup.
"""
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.brand import Brand
from app.models.location import OrgUnit, OrgTier

TENANT_NAME = "Life & Brand Portfolio"
BRAND_NAMES = ["Tiger's Milk", "La Parada", "Harbour House"]
AREA_NAME = "Cape Town Area"
AREA_POS_CODE = "AREA-CT"

# (pos_site_code, name, brand name)
SITES: list[tuple[str, str, str]] = [
    ("HHCB", "Harbour House Camps Bay", "Harbour House"),
    ("TMCB", "Tiger's Milk Camps Bay", "Tiger's Milk"),
    ("TMKS", "Tiger's Milk Kloof Street", "Tiger's Milk"),
    ("TMGP", "Tiger's Milk Green Point", "Tiger's Milk"),
    ("LPKS", "La Parada Kloof Street", "La Parada"),
    ("TMLS", "Tiger's Milk Long Street", "Tiger's Milk"),
]


def seed_org(db: Session) -> None:
    """Ensure tenant, brands, area and site org units exist. Idempotent."""
    # ── Tenant ────────────────────────────────────────────────────────────────
    tenant = db.query(Tenant).filter(Tenant.name == TENANT_NAME).first()
    if tenant is None:
        tenant = Tenant(name=TENANT_NAME)
        db.add(tenant)
        db.flush()

    # ── Brands ────────────────────────────────────────────────────────────────
    brands: dict[str, Brand] = {}
    for brand_name in BRAND_NAMES:
        brand = db.query(Brand).filter(Brand.name == brand_name).first()
        if brand is None:
            brand = Brand(name=brand_name)
            db.add(brand)
            db.flush()
        brands[brand_name] = brand

    # ── Area org unit ─────────────────────────────────────────────────────────
    area = db.query(OrgUnit).filter(OrgUnit.pos_site_code == AREA_POS_CODE).first()
    if area is None:
        area = db.query(OrgUnit).filter(OrgUnit.name == AREA_NAME).first()
    if area is None:
        area = OrgUnit(
            name=AREA_NAME,
            tier=OrgTier.AREA,
            pos_site_code=AREA_POS_CODE,
            tenant_id=tenant.id,
        )
        db.add(area)
        db.flush()
    else:
        area.tier = OrgTier.AREA
        area.pos_site_code = AREA_POS_CODE
        if area.tenant_id is None:
            area.tenant_id = tenant.id

    # ── Site org units ────────────────────────────────────────────────────────
    for pos_code, site_name, brand_name in SITES:
        site = db.query(OrgUnit).filter(OrgUnit.pos_site_code == pos_code).first()
        if site is None:
            site = db.query(OrgUnit).filter(OrgUnit.name == site_name).first()
        if site is None:
            site = OrgUnit(
                name=site_name,
                tier=OrgTier.SITE,
                pos_site_code=pos_code,
                parent_id=area.id,
                brand_id=brands[brand_name].id,
                tenant_id=tenant.id,
            )
            db.add(site)
        else:
            site.pos_site_code = pos_code
            if site.parent_id is None:
                site.parent_id = area.id
            if site.brand_id is None:
                site.brand_id = brands[brand_name].id
            if site.tenant_id is None:
                site.tenant_id = tenant.id

    db.commit()
