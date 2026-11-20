from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClassificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    provider: str
    model: str | None
    prompt_version: str
    category: str | None
    subcategory: str | None
    intent: str | None
    priority: str | None
    language: str | None
    is_injection: bool | None
    confidence: float | None
    requires_human: bool
    explanation: str | None
    error: str | None
    created_at: datetime


class RoutingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lane: str
    queue: str
    support_level: str
    rule_id: str
    rule_version: str
    reason: str
    requires_approval: bool
    inputs: dict[str, Any]
    decided_at: datetime


class IncidentLinkOut(BaseModel):
    ticket_id: uuid.UUID
    external_id: str | None
    channel: str
    created_at: datetime
    subject_redacted: str | None
    role: str
    rule_id: str
    reason: str
    confidence: float
    active: bool
    manual: bool


class IncidentOut(BaseModel):
    id: uuid.UUID
    kind: str
    customer_id: str | None
    customer_name: str | None
    region: str | None
    master_external_id: str | None
    owner_queue: str | None
    category: str | None
    rule_id: str
    first_ticket_at: datetime
    declared_at: datetime
    status: str
    ticket_count: int


class IncidentDetail(IncidentOut):
    links: list[IncidentLinkOut]


class LinkRequest(BaseModel):
    ticket_ref: str = Field(min_length=1, max_length=40)


class ProcessResult(BaseModel):
    classification: ClassificationOut
    routing: RoutingOut


class TicketRouting(BaseModel):
    classification: ClassificationOut | None
    routing: RoutingOut | None
    incidents: list[IncidentOut]
