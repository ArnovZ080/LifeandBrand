"""
Approval engine (Feature 2).

ApprovalRule decides which levels must approve a subject (a requisition or a
purchase order) for a given order value at a given org unit. Levels are an
ordered list of UserRole values. ApprovalRequest is the in-flight instance; it
copies the levels from the rule when opened, so later rule edits do not change
approvals already in progress.
"""
from datetime import datetime
import enum
from typing import Optional
from sqlalchemy import (
    String, DateTime, Boolean, Numeric, ForeignKey, Text, Enum, Integer, JSON, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class ApprovalSubject(str, enum.Enum):
    REQUISITION = "REQUISITION"
    PURCHASE_ORDER = "PURCHASE_ORDER"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DecisionOutcome(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalRule(Base):
    __tablename__ = "approval_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[ApprovalSubject] = mapped_column(
        Enum(ApprovalSubject, name="approvalsubject"), nullable=False,
    )
    # null = applies to every site; a rule on a parent unit covers its descendants
    org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    # Range is min_value <= value < max_value; max_value null = no upper bound
    min_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    max_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    levels: Mapped[list[str]] = mapped_column(JSON, nullable=False)  # ordered UserRole values, 1-5
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org_unit: Mapped[Optional["OrgUnit"]] = relationship()


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("subject", "subject_id", name="uq_approval_requests_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[ApprovalSubject] = mapped_column(
        Enum(ApprovalSubject, name="approvalsubject"), nullable=False,
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("approval_rules.id"), nullable=True)
    levels: Mapped[list[str]] = mapped_column(JSON, nullable=False)  # copied from the rule
    current_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1-based
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approvalstatus"), default=ApprovalStatus.PENDING, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    rule: Mapped[Optional["ApprovalRule"]] = relationship()
    org_unit: Mapped["OrgUnit"] = relationship()
    decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="approval_request", cascade="all, delete-orphan",
        order_by="ApprovalDecision.id",
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_request_id: Mapped[int] = mapped_column(ForeignKey("approval_requests.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_name: Mapped[str] = mapped_column(String(120), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[DecisionOutcome] = mapped_column(
        Enum(DecisionOutcome, name="decisionoutcome"), nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    approval_request: Mapped["ApprovalRequest"] = relationship(back_populates="decisions")
