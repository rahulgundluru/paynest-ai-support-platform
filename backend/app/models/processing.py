"""AI-pipeline outputs: classifications, routing decisions, incidents/duplicate links, model usage."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

LANES = ("auto_answer", "draft_for_agent", "route_queue", "incident", "human_review", "block")


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # ok | invalid | failed | unavailable
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str | None] = mapped_column(String(20))
    subcategory: Mapped[str | None] = mapped_column(String(80))
    intent: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[str | None] = mapped_column(String(2))
    language: Mapped[str | None] = mapped_column(String(12))
    is_injection: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[float | None] = mapped_column(Float)
    requires_human: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint("status IN ('ok', 'invalid', 'failed', 'unavailable')", name="status"),)


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lane: Mapped[str] = mapped_column(String(20), nullable=False)
    queue: Mapped[str] = mapped_column(String(40), nullable=False)
    support_level: Mapped[str] = mapped_column(String(12), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (CheckConstraint(f"lane IN ({', '.join(repr(v) for v in LANES)})", name="lane"),)


class Incident(Base):
    """A group of tickets handled as ONE case: a resubmission chain or a multi-ticket incident."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # resubmission | incident
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    region: Mapped[str | None] = mapped_column(String(3), index=True)
    master_ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    owner_queue: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(20))
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(30), nullable=False)
    first_ticket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    links: Mapped[list[IncidentLink]] = relationship(cascade="all, delete-orphan", order_by="IncidentLink.id")

    __table_args__ = (
        CheckConstraint("kind IN ('resubmission', 'incident')", name="kind"),
        CheckConstraint("status IN ('open', 'closed', 'dissolved')", name="status"),
    )


class IncidentLink(Base):
    __tablename__ = "incident_links"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # master | member | resubmit
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))  # null = automatic
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("incident_id", "ticket_id", name="uq_incident_links_incident_ticket"),
        CheckConstraint("role IN ('master', 'member', 'resubmit')", name="role"),
    )


class ModelUsage(Base):
    """One row per model call attempt (successful or not). Never holds prompt or response text."""

    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # classify | embed | draft | judge
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), index=True)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Named "estimated" for history; `cost_source` says whether the provider reported it or a price table.
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cost_source: Mapped[str | None] = mapped_column(String(20))  # provider_reported | price_table
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(40))  # short code, never message text from a ticket
    request_id: Mapped[str | None] = mapped_column(String(80))
    upstream_provider: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


PIPELINE_TRIGGERS = ("create", "rerun")
PIPELINE_STATES = ("running", "completed", "failed")


class PipelineRun(Base):
    """One end-to-end pass of a ticket through the pipeline, with a timed record of every step.

    `steps` is an ordered list of {key, label, status, summary, details, started_at, duration_ms, cost_usd}.
    Step statuses: pending | running | done | skipped | blocked | failed | review. Details hold identifiers,
    counts and decisions only, never ticket text or PII values."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    error: Mapped[str | None] = mapped_column(String(200))
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"trigger IN ({', '.join(repr(v) for v in PIPELINE_TRIGGERS)})", name="trigger"),
        CheckConstraint(f"status IN ({', '.join(repr(v) for v in PIPELINE_STATES)})", name="status"),
    )
