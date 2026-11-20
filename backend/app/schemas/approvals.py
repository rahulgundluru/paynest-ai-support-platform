from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApprovalEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    from_status: str | None
    to_status: str
    actor_user_id: uuid.UUID | None
    note: str | None
    details: dict[str, Any]
    occurred_at: datetime


class ApprovalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    ticket_external_id: str | None = None
    region: str | None
    status: str
    lane: str
    queue: str
    rule_id: str
    escalation_reason: str
    summary: str = ""
    sla_breached: bool | None = None
    draft_source: str
    validation_passed: bool | None = None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDetail(ApprovalSummary):
    evidence: dict[str, Any]
    draft_text: str | None
    validation: dict[str, Any] | None
    events: list[ApprovalEventOut]
    requires_second_person: bool


class DraftRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject", "escalate", "reassign", "resolve"]
    note: str | None = Field(default=None, max_length=2000)
    target: str | None = Field(default=None, max_length=40)


class RevealRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class RevealResponse(BaseModel):
    token: str
    entity_type: str
    value: str
    revealed_at: datetime
    retention_until: datetime


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    customer_id: str | None
    region: str | None
    category: str | None
    resolution_text: str
    cited_versions: list[dict[str, Any]]
    valid_until: date | None
    created_at: datetime
