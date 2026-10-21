"""Approval rule management (Feature 2).

Creating or editing a rule changes who must approve future orders, so only
national_ops, md and ceo may do it; global rules (no org unit) are reserved for
md and ceo. Editing a rule never changes approvals already in flight.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models.approval import ApprovalRule, ApprovalSubject
from app.models.user import User
from app.services import approval_service
from app.services.approval_service import ConflictError

router = APIRouter(prefix="/approval-rules", tags=["approval-rules"])


class RuleCreate(BaseModel):
    subject: ApprovalSubject
    org_unit_id: int | None = None  # null = all sites
    min_value: float = 0
    max_value: float | None = None  # null = no upper bound
    levels: list[str]  # ordered UserRole values, 1 to 5 entries
    active: bool = True


class RulePatch(BaseModel):
    # Only fields present in the request body are changed.
    org_unit_id: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    levels: list[str] | None = None
    active: bool | None = None


class RuleOut(BaseModel):
    id: int
    subject: ApprovalSubject
    org_unit_id: int | None
    min_value: float
    max_value: float | None
    levels: list[str]
    active: bool
    created_at: datetime

    @classmethod
    def from_rule(cls, r: ApprovalRule) -> "RuleOut":
        return cls(
            id=r.id,
            subject=r.subject,
            org_unit_id=r.org_unit_id,
            min_value=float(r.min_value),
            max_value=float(r.max_value) if r.max_value is not None else None,
            levels=list(r.levels),
            active=r.active,
            created_at=r.created_at,
        )


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


@router.post("/", response_model=RuleOut, status_code=201)
def create_rule(
    body: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not approval_service.can_manage_rule(db, current_user, body.org_unit_id):
        raise HTTPException(403, "Your role cannot create this approval rule")
    rule = _call(
        approval_service.create_rule, db,
        subject=body.subject, org_unit_id=body.org_unit_id,
        min_value=body.min_value, max_value=body.max_value,
        levels=body.levels, active=body.active, actor=current_user,
    )
    return RuleOut.from_rule(rule)


@router.get("/", response_model=list[RuleOut])
def list_rules(
    subject: ApprovalSubject | None = None,
    active: bool | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ApprovalRule)
    if subject is not None:
        query = query.filter(ApprovalRule.subject == subject)
    if active is not None:
        query = query.filter(ApprovalRule.active.is_(active))
    return [RuleOut.from_rule(r) for r in query.order_by(ApprovalRule.id).all()]


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int,
    body: RulePatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Approval rule not found")
    changes = body.model_dump(exclude_unset=True)
    # Check both the rule's current unit and any unit it is being moved to.
    targets = {rule.org_unit_id}
    if "org_unit_id" in changes:
        targets.add(changes["org_unit_id"])
    for unit_id in targets:
        if not approval_service.can_manage_rule(db, current_user, unit_id):
            raise HTTPException(403, "Your role cannot change this approval rule")
    updated = _call(approval_service.update_rule, db, rule, changes, actor=current_user)
    return RuleOut.from_rule(updated)
