"""Ingestion provenance, canonical tickets, PII redaction records and SLA tracking.

Every free-text column here holds REDACTED text only. Original values live encrypted in
`pii_vault` (per token) and `source_records.raw_encrypted` (whole record).
"""

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
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

CHANNELS = ("email", "widget", "partner_portal", "whatsapp", "phone")
RECORD_STATUSES = ("pending", "processing", "processed", "failed", "requires_review", "duplicate", "skipped")
CATEGORIES = (
    "payroll",
    "statutory",
    "how_to",
    "reports",
    "leave_attendance",
    "integration",
    "billing",
    "access_login",
    "onboarding",
)
CUSTOMER_RESOLUTIONS = ("direct", "partner_end_customer_name", "whatsapp_customer_hint", "unresolved")
EVENT_TYPES = ("created", "assigned", "replied", "reassigned", "escalated", "reopened", "resolved")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source_commit: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (CheckConstraint("status IN ('running', 'completed', 'failed')", name="status"),)


class SourceRecord(Base):
    """One row per record read from a source file (never discarded, whatever its outcome)."""

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_batches.id"), nullable=False, index=True)
    source_file: Mapped[str] = mapped_column(String(200), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(20), index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    region: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    status_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    duplicate_of_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"))
    raw_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_file", "record_index", name="uq_source_records_file_index"),
        CheckConstraint(_in("status", RECORD_STATUSES), name="status"),
        CheckConstraint(_in("channel", CHANNELS), name="channel"),
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    customer_resolution: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str | None] = mapped_column(String(3), index=True)
    region_source: Mapped[str | None] = mapped_column(String(32))
    partner_id: Mapped[str | None] = mapped_column(String(10))

    subject_redacted: Mapped[str | None] = mapped_column(Text)
    body_redacted: Mapped[str | None] = mapped_column(Text)
    language_hint: Mapped[str | None] = mapped_column(String(12))

    priority: Mapped[str | None] = mapped_column(String(2), index=True)
    customer_category: Mapped[str | None] = mapped_column(String(20), index=True)
    # The export's header category is the FINAL (post-reassignment) label. Stored for evaluation
    # only; it must never be used as a classifier input (label leakage).
    final_category_label: Mapped[str | None] = mapped_column(String(20))
    first_queue: Mapped[str | None] = mapped_column(String(40))
    final_queue: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str | None] = mapped_column(String(12))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reassignment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_payroll_window: Mapped[bool] = mapped_column(Boolean, nullable=False)

    ingestion_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # import = from the pinned source data (the evaluation set); app = entered through the New ticket screen.
    origin: Mapped[str] = mapped_column(
        String(8), nullable=False, default="import", server_default="import", index=True
    )
    review_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[list[TicketMessage]] = relationship(order_by="TicketMessage.seq", cascade="all, delete-orphan")
    events: Mapped[list[TicketEvent]] = relationship(order_by="TicketEvent.seq", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(_in("channel", CHANNELS), name="channel"),
        CheckConstraint("priority IS NULL OR priority IN ('P1', 'P2', 'P3')", name="priority"),
        CheckConstraint(f"customer_category IS NULL OR {_in('customer_category', CATEGORIES)}", name="category"),
        CheckConstraint(_in("customer_resolution", CUSTOMER_RESOLUTIONS), name="customer_resolution"),
        CheckConstraint("region IS NULL OR region IN ('IN', 'UAE')", name="region"),
        CheckConstraint(_in("ingestion_status", RECORD_STATUSES), name="ingestion_status"),
        CheckConstraint("origin IN ('import', 'app')", name="origin"),
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    author_type: Mapped[str] = mapped_column(String(10), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body_redacted: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticket_id", "seq", name="uq_ticket_messages_ticket_seq"),
        CheckConstraint("author_type IN ('customer', 'agent', 'system')", name="author_type"),
    )


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(12), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("ticket_id", "seq", name="uq_ticket_events_ticket_seq"),
        CheckConstraint(_in("event_type", EVENT_TYPES), name="event_type"),
    )


class NormalizationLog(Base):
    """Original value, normalized value and the rule that mapped it. Structured fields only, never free text."""

    __tablename__ = "normalization_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    original_value: Mapped[str | None] = mapped_column(String(200))
    normalized_value: Mapped[str | None] = mapped_column(String(200))
    rule: Mapped[str] = mapped_column(String(60), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PiiDetection(Base):
    """Where a PII value was found and which token replaced it. Holds no raw value."""

    __tablename__ = "pii_detections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(30), nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    checksum_valid: Mapped[bool | None] = mapped_column(Boolean)


class PiiVaultEntry(Base):
    """Encrypted original value per (source record, token). Region-tagged for residency and retention."""

    __tablename__ = "pii_vault"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    region: Mapped[str | None] = mapped_column(String(3))
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("source_record_id", "token", name="uq_pii_vault_record_token"),)


class SlaTracking(Base):
    __tablename__ = "sla_tracking"

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    not_applicable_reason: Mapped[str | None] = mapped_column(String(60))
    template_version: Mapped[str | None] = mapped_column(String(8))
    tier: Mapped[str | None] = mapped_column(String(12))
    priority: Mapped[str | None] = mapped_column(String(2))
    first_response_target_h: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    resolution_target_h: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    resolution_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    first_response_breached: Mapped[bool | None] = mapped_column(Boolean)
    resolution_breached: Mapped[bool | None] = mapped_column(Boolean, index=True)
    severity_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    credit_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    credit_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
