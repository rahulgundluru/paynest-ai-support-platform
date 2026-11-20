"""Ticket API contracts. Only redacted text and PII tokens are ever exposed; never raw values."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class SlaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    applicable: bool
    not_applicable_reason: str | None
    template_version: str | None
    tier: str | None
    priority: str | None
    first_response_target_h: Decimal | None
    resolution_target_h: Decimal | None
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    first_response_hours: Decimal | None
    resolution_hours: Decimal | None
    first_response_breached: bool | None
    resolution_breached: bool | None
    severity_multiplier: Decimal | None
    credit_pct: Decimal | None
    credit_usd: Decimal | None
    rule_version: str


class TicketSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None
    channel: str
    customer_id: str | None
    customer_name: str | None = None
    customer_tier: str | None = None
    region: str | None
    subject_redacted: str | None
    priority: str | None
    customer_category: str | None
    first_queue: str | None
    final_queue: str | None
    status: str | None
    created_at: datetime
    reassignment_count: int
    reopen_count: int
    in_payroll_window: bool
    ingestion_status: str
    pii_entity_count: int = 0
    sla_resolution_breached: bool | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    author_type: str
    sent_at: datetime | None
    body_redacted: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_type: str
    occurred_at: datetime
    actor: str | None
    data: dict[str, Any]


class PiiDetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    entity_type: str
    token: str
    method: str
    confidence: float
    checksum_valid: bool | None


class NormalizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    original_value: str | None
    normalized_value: str | None
    rule: str


class TicketDetail(TicketSummary):
    customer_resolution: str
    region_source: str | None
    partner_id: str | None
    body_redacted: str | None
    language_hint: str | None
    final_category_label: str | None
    first_response_at: datetime | None
    resolved_at: datetime | None
    review_reasons: list[str]
    attributes: dict[str, Any]
    source_file: str
    source_record_index: int
    messages: list[MessageOut]
    events: list[EventOut]
    pii_detections: list[PiiDetectionOut]
    normalization: list[NormalizationOut]
    sla: SlaOut | None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    name: str
    tier: str
    region: str
    monthly_fee_usd: Decimal
    employees_paid: int | None
    ticket_count: int = 0
    sla_breaches: int = 0
    credits_usd: Decimal = Decimal("0")


class SlaTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_version: str
    tier: str
    priority: str
    first_response_h: Decimal
    resolution_h: Decimal
    credit_pct: Decimal
    source: str


class CustomerDetail(CustomerOut):
    sla_terms: list[SlaTermOut]


class ReconciliationRow(BaseModel):
    breach_id: str
    ticket_external_id: str
    finance_credit_usd: Decimal
    engine_credit_usd: Decimal | None
    finance_actual_h: Decimal
    engine_resolution_h: Decimal | None
    matches: bool


class Reconciliation(BaseModel):
    finance_rows: int
    matched: int
    mismatched: int
    finance_total_usd: Decimal
    engine_total_for_finance_rows_usd: Decimal
    engine_breaches_not_in_finance_list: list[str]
    rows: list[ReconciliationRow]


class IngestionBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    status: str
    source_commit: str | None
    summary: dict[str, Any]
