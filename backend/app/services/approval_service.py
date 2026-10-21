"""
Approval engine (Feature 2).

Error convention shared by the requisition services and the routes:
  LookupError     -> 404 (unknown org unit, rule, request)
  PermissionError -> 403 (approver has the wrong role or is outside its org scope)
  ConflictError   -> 409 (state does not allow the action, or an overlapping rule)
  ValueError      -> 400 (invalid input)

Matching rules
--------------
A rule matches a value when min_value <= value < max_value (max_value null =
no upper bound). Among the active rules that match, the most specific wins:
a rule on the requesting unit beats one on its parent, which beats one on
its grandparent, and so on up to the root; global rules (org_unit_id null)
are the least specific. Overlapping active rules for the same subject and
org unit are refused, so the winner is unambiguous.

Callers own the transaction: open_request and decide only flush. The public
service functions in requisition_service commit.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_subtree_ids
from app.models.approval import (
    ApprovalDecision, ApprovalRequest, ApprovalRule, ApprovalStatus,
    ApprovalSubject, DecisionOutcome,
)
from app.models.location import OrgUnit
from app.models.purchase_order import POStatus, PurchaseOrder
from app.models.requisition import Requisition, RequisitionStatus
from app.models.user import User, UserRole

MIN_LEVELS = 1
MAX_LEVELS = 5
VALID_ROLES = {role.value for role in UserRole}


class ConflictError(Exception):
    """The action conflicts with the current state (HTTP 409)."""


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _ancestor_chain(db: Session, org_unit_id: int) -> list[int]:
    """The unit itself, then its parent, grandparent, ... up to the root."""
    if db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    chain: list[int] = []
    current_id: int | None = org_unit_id
    while current_id is not None and current_id not in chain:
        chain.append(current_id)
        current_id = db.get(OrgUnit, current_id).parent_id
    return chain


def user_covers_unit(db: Session, user: User, org_unit_id: int) -> bool:
    """True when org_unit_id is inside the user's own org subtree."""
    return org_unit_id in get_subtree_ids(db, user.org_unit_id)


def _in_range(rule: ApprovalRule, value: Decimal) -> bool:
    if value < _dec(rule.min_value):
        return False
    return rule.max_value is None or value < _dec(rule.max_value)


def find_rule(
    db: Session, subject: ApprovalSubject, org_unit_id: int, value,
) -> ApprovalRule | None:
    """The most specific active rule for subject, unit and value, or None."""
    chain = _ancestor_chain(db, org_unit_id)
    amount = _dec(value)
    rules = db.execute(
        select(ApprovalRule).where(
            ApprovalRule.subject == subject,
            ApprovalRule.active.is_(True),
        )
    ).scalars().all()

    def specificity(rule: ApprovalRule) -> int | None:
        if rule.org_unit_id is None:
            return len(chain)  # global: least specific
        if rule.org_unit_id in chain:
            return chain.index(rule.org_unit_id)  # 0 = requesting unit
        return None  # rule belongs to another branch of the tree

    candidates = []
    for rule in rules:
        rank = specificity(rule)
        if rank is not None and _in_range(rule, amount):
            candidates.append((rank, rule.id, rule))
    if not candidates:
        return None
    return min(candidates, key=lambda c: (c[0], c[1]))[2]


def open_request(
    db: Session, subject: ApprovalSubject, subject_id: int, org_unit_id: int, value,
) -> ApprovalRequest | None:
    """Open an approval for the subject if a rule matches; None means no approval is needed."""
    rule = find_rule(db, subject, org_unit_id, value)
    if rule is None:
        return None
    existing = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.subject == subject,
            ApprovalRequest.subject_id == subject_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"An approval request already exists for {subject.value} {subject_id}")
    request = ApprovalRequest(
        subject=subject,
        subject_id=subject_id,
        org_unit_id=org_unit_id,
        rule_id=rule.id,
        levels=list(rule.levels),  # copied so later rule edits do not change this approval
        current_level=1,
        status=ApprovalStatus.PENDING,
    )
    db.add(request)
    db.flush()
    return request


def get_request(db: Session, subject: ApprovalSubject, subject_id: int) -> ApprovalRequest | None:
    return db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.subject == subject,
            ApprovalRequest.subject_id == subject_id,
        )
    ).scalar_one_or_none()


def _settle_subject(db: Session, request: ApprovalRequest, approved: bool) -> None:
    """Carry the final outcome back to the subject."""
    if request.subject == ApprovalSubject.REQUISITION:
        requisition = db.get(Requisition, request.subject_id)
        requisition.status = RequisitionStatus.APPROVED if approved else RequisitionStatus.REJECTED
    elif request.subject == ApprovalSubject.PURCHASE_ORDER:
        # POStatus has no "approved" state, so an approved PO stays DRAFT until the buyer
        # sends it. A rejected PO is cancelled.
        if not approved:
            purchase_order = db.get(PurchaseOrder, request.subject_id)
            purchase_order.status = POStatus.CANCELLED


def decide(
    db: Session,
    request: ApprovalRequest,
    approver: User,
    decision: DecisionOutcome,
    comment: str | None = None,
) -> ApprovalDecision:
    """Record one level's decision and advance, approve or reject the request.

    Raises ConflictError if the request is closed, PermissionError if the
    approver's role is not the current level's role or the approver's org
    subtree does not contain the request's unit.
    """
    if request.status != ApprovalStatus.PENDING or request.closed_at is not None:
        raise ConflictError("This approval request is already closed")

    levels = list(request.levels)
    if not 1 <= request.current_level <= len(levels):
        raise ConflictError("Approval request has no level awaiting a decision")
    required_role = levels[request.current_level - 1]
    if approver.role.value != required_role:
        raise PermissionError(
            f"Level {request.current_level} requires role '{required_role}', "
            f"not '{approver.role.value}'"
        )
    if not user_covers_unit(db, approver, request.org_unit_id):
        raise PermissionError("Approver's org unit does not cover this request's unit")

    row = ApprovalDecision(
        approval_request_id=request.id,
        level=request.current_level,
        approver_name=approver.name,
        approver_role=approver.role.value,
        decision=decision,
        comment=comment,
        decided_at=datetime.utcnow(),
    )
    db.add(row)

    if decision == DecisionOutcome.REJECTED:
        request.status = ApprovalStatus.REJECTED
        request.closed_at = datetime.utcnow()
        _settle_subject(db, request, approved=False)
    elif request.current_level == len(levels):
        request.status = ApprovalStatus.APPROVED
        request.closed_at = datetime.utcnow()
        _settle_subject(db, request, approved=True)
    else:
        request.current_level += 1

    db.flush()
    return row


# ── Rule validation and management ────────────────────────────────────────────

def validate_levels(levels) -> list[str]:
    if not isinstance(levels, list) or not MIN_LEVELS <= len(levels) <= MAX_LEVELS:
        raise ValueError(f"levels must contain {MIN_LEVELS} to {MAX_LEVELS} roles")
    bad = [level for level in levels if not isinstance(level, str) or level not in VALID_ROLES]
    if bad:
        raise ValueError(f"Invalid role(s) in levels: {bad}. Valid roles: {sorted(VALID_ROLES)}")
    return list(levels)


def validate_range(min_value, max_value) -> None:
    if min_value is None:
        raise ValueError("min_value cannot be null")
    if _dec(min_value) < 0:
        raise ValueError("min_value cannot be negative")
    if max_value is not None and _dec(max_value) <= _dec(min_value):
        raise ValueError("max_value must be greater than min_value")


def _ranges_overlap(a_min, a_max, b_min, b_max) -> bool:
    """Half-open ranges [min, max); a null max is unbounded."""
    a_min, b_min = _dec(a_min), _dec(b_min)
    a_starts_before_b_ends = b_max is None or a_min < _dec(b_max)
    b_starts_before_a_ends = a_max is None or b_min < _dec(a_max)
    return a_starts_before_b_ends and b_starts_before_a_ends


def _check_no_overlap(
    db: Session,
    rule_id: int | None,
    subject: ApprovalSubject,
    org_unit_id: int | None,
    min_value,
    max_value,
) -> None:
    query = select(ApprovalRule).where(
        ApprovalRule.subject == subject,
        ApprovalRule.active.is_(True),
    )
    if org_unit_id is None:
        query = query.where(ApprovalRule.org_unit_id.is_(None))
    else:
        query = query.where(ApprovalRule.org_unit_id == org_unit_id)
    if rule_id is not None:
        query = query.where(ApprovalRule.id != rule_id)
    for other in db.execute(query).scalars():
        if _ranges_overlap(min_value, max_value, other.min_value, other.max_value):
            raise ConflictError(
                f"Overlaps active rule {other.id} for the same subject and org unit"
            )


def create_rule(
    db: Session,
    *,
    subject: ApprovalSubject,
    org_unit_id: int | None,
    min_value=0,
    max_value=None,
    levels,
    active: bool = True,
) -> ApprovalRule:
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")
    levels = validate_levels(levels)
    validate_range(min_value, max_value)
    if active:
        _check_no_overlap(db, None, subject, org_unit_id, min_value, max_value)
    rule = ApprovalRule(
        subject=subject,
        org_unit_id=org_unit_id,
        min_value=_dec(min_value),
        max_value=_dec(max_value) if max_value is not None else None,
        levels=levels,
        active=active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


_RULE_FIELDS = {"org_unit_id", "min_value", "max_value", "levels", "active"}


def update_rule(db: Session, rule: ApprovalRule, changes: dict) -> ApprovalRule:
    """Apply only the keys present in changes. Requests already in flight keep their copied levels."""
    unknown = set(changes) - _RULE_FIELDS
    if unknown:
        raise ValueError(f"Unknown rule field(s): {sorted(unknown)}")

    org_unit_id = changes.get("org_unit_id", rule.org_unit_id)
    min_value = changes.get("min_value", rule.min_value)
    max_value = changes.get("max_value", rule.max_value)
    active = changes.get("active", rule.active)
    if active is None:
        raise ValueError("active cannot be null")
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise LookupError(f"Org unit {org_unit_id} not found")

    validate_range(min_value, max_value)
    if "levels" in changes:
        levels = validate_levels(changes["levels"])
    else:
        levels = list(rule.levels)

    if active:
        _check_no_overlap(db, rule.id, rule.subject, org_unit_id, min_value, max_value)

    rule.org_unit_id = org_unit_id
    rule.min_value = _dec(min_value)
    rule.max_value = _dec(max_value) if max_value is not None else None
    rule.levels = levels
    rule.active = bool(active)
    db.commit()
    db.refresh(rule)
    return rule


# Who may create or change approval rules. Global rules are reserved for MD and CEO.
RULE_ADMIN_ROLES = {UserRole.NATIONAL_OPS, UserRole.MD, UserRole.CEO}
GLOBAL_RULE_ROLES = {UserRole.MD, UserRole.CEO}


def can_manage_rule(db: Session, user: User, org_unit_id: int | None) -> bool:
    if user.role not in RULE_ADMIN_ROLES:
        return False
    if org_unit_id is None:
        return user.role in GLOBAL_RULE_ROLES
    return user_covers_unit(db, user, org_unit_id)
