from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.location import OrgUnit, OrgTier
from app.models.brand import Brand
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/org-units", tags=["org-units"])


class OrgUnitCreate(BaseModel):
    name: str
    code: str | None = None
    tier: OrgTier = OrgTier.SITE
    parent_id: int | None = None
    brand_id: int | None = None
    pos_site_code: str | None = None


class OrgUnitOut(BaseModel):
    id: int
    name: str
    code: str | None
    tier: str
    parent_id: int | None
    brand_id: int | None
    is_active: bool
    children: list["OrgUnitOut"] = []

    class Config:
        from_attributes = True


OrgUnitOut.model_rebuild()


class BrandCreate(BaseModel):
    name: str


class BrandOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


def _build_tree(units: list[OrgUnit]) -> list[OrgUnitOut]:
    by_id = {u.id: OrgUnitOut(
        id=u.id, name=u.name, code=u.code, tier=u.tier.value,
        parent_id=u.parent_id, brand_id=u.brand_id, is_active=u.is_active,
    ) for u in units}
    roots = []
    for node in by_id.values():
        if node.parent_id and node.parent_id in by_id:
            by_id[node.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.get("/tree", response_model=list[OrgUnitOut])
def get_tree(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    units = db.query(OrgUnit).filter(OrgUnit.is_active == True).all()
    return _build_tree(units)


@router.get("/", response_model=list[OrgUnitOut])
def list_units(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    units = db.query(OrgUnit).filter(OrgUnit.is_active == True).order_by(OrgUnit.name).all()
    return [OrgUnitOut(
        id=u.id, name=u.name, code=u.code, tier=u.tier.value,
        parent_id=u.parent_id, brand_id=u.brand_id, is_active=u.is_active,
    ) for u in units]


@router.post("/", response_model=OrgUnitOut, status_code=201)
def create_unit(
    payload: OrgUnitCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    unit = OrgUnit(**payload.model_dump())
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return OrgUnitOut(
        id=unit.id, name=unit.name, code=unit.code, tier=unit.tier.value,
        parent_id=unit.parent_id, brand_id=unit.brand_id, is_active=unit.is_active,
    )


# ── Brands ─────────────────────────────────────────────────────────────────────

@router.get("/brands", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Brand).order_by(Brand.name).all()


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(
    payload: BrandCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    brand = Brand(name=payload.name)
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand
