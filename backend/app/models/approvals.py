"""Human-in-the-loop review items, their full action history, and human-approved learned memory.

The workflow state lives in PostgreSQL, so a pending review survives restarts and resumes exactly
where it stopped (Session 4: "a P1 draft can wait minutes or hours for a reviewer").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

APPROVAL_STATES = ("pending", "approved", "rejected", "escalated", "resolved")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    routing_decision_id: Mapped[int | None] = mapped_column(ForeignKey("routing_decisions.id", ondelete="SET NULL"))
    region: Mapped[str | None] = mapped_column(String(3), index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", index=True)
    lane: Mapped[str] = mapped_column(String(20), nullable=False)
    queue: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    escalation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draft_text: Mapped[str | None] = mapped_column(Text)  # redacted: tokens only, re-hydrated only at send
    draft_source: Mapped[str] = mapped_column(String(10), nullable=False, default="none")  # none | ai | human
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[ApprovalEvent]] = relationship(order_by="ApprovalEvent.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in APPROVAL_STATES)})", name="status"),
        CheckConstraint("draft_source IN ('none', 'ai', 'human')", name="draft_source"),
    )


class ApprovalEvent(Base):
    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LearnedMemory(Base):
    """Reusable resolution patterns. Written ONLY from human-approved responses; never from raw AI output.
    Expires when any policy version it relied on stops being in force."""

    __tablename__ = "learned_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(10))  # scope: never shown to another customer
    region: Mapped[str | None] = mapped_column(String(3), index=True)
    category: Mapped[str | None] = mapped_column(String(20), index=True)
    resolution_text: Mapped[str] = mapped_column(Text, nullable=False)  # redacted
    cited_versions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    valid_until: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
