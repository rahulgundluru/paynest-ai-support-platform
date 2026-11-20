from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tickets import CATEGORIES, CHANNELS


class NewTicketRequest(BaseModel):
    channel: Literal["email", "widget", "partner_portal", "whatsapp", "phone"]
    customer_id: str | None = Field(default=None, max_length=10, description="Customer master id, e.g. C-1012")
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=5, max_length=5000)
    priority: Literal["P1", "P2", "P3"] | None = None
    customer_category: str | None = Field(default=None, description="The customer's own pick, if they gave one")
    received_at: datetime | None = Field(default=None, description="When the customer sent it; defaults to now")

    @field_validator("customer_category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if value not in CATEGORIES:
            raise ValueError(f"customer_category must be one of {list(CATEGORIES)}")
        return value

    @field_validator("customer_id")
    @classmethod
    def _customer(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("received_at")
    @classmethod
    def _received(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("received_at must include a timezone offset")
        if value > datetime.now(tz=UTC):
            raise ValueError("received_at cannot be in the future")
        if value.year < 2026:
            raise ValueError("received_at must be in 2026 or later (the knowledge base starts in 2026)")
        return value


assert set(CHANNELS) == {"email", "widget", "partner_portal", "whatsapp", "phone"}  # noqa: S101 - keep in sync


class PipelineStepOut(BaseModel):
    key: str
    label: str
    description: str
    status: str
    summary: str | None
    details: dict[str, Any]
    started_at: str | None
    duration_ms: int | None
    cost_usd: str | None


class PipelineRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_ref: str | None = None
    trigger: str
    status: str
    ai_enabled: bool
    total_cost_usd: Decimal
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    steps: list[PipelineStepOut]


class CreatedTicket(BaseModel):
    ticket_ref: str
    run: PipelineRunOut
