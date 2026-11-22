"""Par levels per site (shopping list feature).

Reads and writes are scoped to the caller's org subtree. An out-of-subtree
org unit gets 403 (get_accessible_org_unit_ids), and an out-of-subtree par
record gets 403 on write. Only site org units hold pars; other tiers get 400.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user, get_subtree_ids
from app.db.database import get_db
from app.models import Item, OrgUnit
from app.models.par_level import ParLevel
from app.models.user import User
from app.services.approval_service import ConflictError
from app.services.par_service import delete_par, list_pars, upsert_par

router = APIRouter(prefix="/par-levels", tags=["par-levels"])


class ParUpsertIn(BaseModel):
    org_unit_id: int
    item_id: int
    par_qty: float = Field(gt=0)
    reorder_point: float = Field(ge=0)


class ParOut(BaseModel):
    id: int
    org_unit_id: int
    item_id: int
    item_code: str
    item_name: str
    unit: str
    par_qty: float
    reorder_point: float
    updated_by: str | None
    updated_at: datetime | None

    @classmethod
    def from_par(cls, par: ParLevel, item: Item) -> "ParOut":
        return cls(
            id=par.id, org_unit_id=par.org_unit_id, item_id=par.item_id,
            item_code=item.code, item_name=item.name,
            unit=item.unit_of_measure.abbreviation if item.unit_of_measure else "",
            par_qty=float(par.par_qty), reorder_point=float(par.reorder_point),
            updated_by=par.updated_by, updated_at=par.updated_at,
        )


class ItemOut(BaseModel):
    id: int
    code: str
    name: str
    unit: str


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ConflictError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/items", response_model=list[ItemOut])
def list_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Active items to choose from when adding a par. Items are tenant-wide, so no org scope applies."""
    items = db.execute(select(Item).where(Item.is_active.is_(True)).order_by(Item.name)).scalars()
    return [
        ItemOut(id=i.id, code=i.code, name=i.name,
                unit=i.unit_of_measure.abbreviation if i.unit_of_measure else "")
        for i in items
    ]


@router.get("/", response_model=list[ParOut])
def list_par_levels(
    org_unit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=current_user, db=db)
    rows = _call(list_pars, db, org_unit_id)
    return [ParOut.from_par(par, item) for par, item in rows]


@router.put("/", response_model=ParOut)
def put_par_level(
    body: ParUpsertIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=body.org_unit_id, current_user=current_user, db=db)
    org_unit = db.get(OrgUnit, body.org_unit_id)
    if org_unit is None:
        raise HTTPException(404, f"Org unit {body.org_unit_id} not found")
    par = _call(
        upsert_par, db, org_unit, body.item_id, body.par_qty, body.reorder_point, current_user,
    )
    return ParOut.from_par(par, db.get(Item, par.item_id))


@router.delete("/{par_id}", response_model=ParOut)
def deactivate_par_level(
    par_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    par = db.get(ParLevel, par_id)
    if par is None:
        raise HTTPException(404, "Par level not found")
    if par.org_unit_id not in get_subtree_ids(db, current_user.org_unit_id):
        raise HTTPException(403, "Access to this org unit is not allowed")
    par = _call(delete_par, db, par, current_user)
    return ParOut.from_par(par, db.get(Item, par.item_id))
