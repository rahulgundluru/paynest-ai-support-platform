"""Evaluation runs (G1-G7), per-case results, and Finance's monthly cost sheet (for the cost model)."""

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
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

GATE_STATUSES = ("pass", "fail", "partial", "not_run")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gate: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_size: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_commit: Mapped[str | None] = mapped_column(String(40))
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint(f"status IN ({', '.join(repr(s) for s in GATE_STATUSES)})", name="status"),)


class EvaluationResult(Base):
    """One evaluated case. `detail` holds identifiers and outcomes only (no ticket text, no PII)."""

    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MonthlyCost(Base):
    """data-room/data/monthly_cost_sheet.csv, verbatim (Finance's figures)."""

    __tablename__ = "monthly_costs"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    tickets_received_all_customers: Mapped[int] = mapped_column(Integer, nullable=False)
    tickets_in_ops_extract: Mapped[int | None] = mapped_column(Integer)
    agent_fte: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_loaded_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tooling_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vendor_pilot_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sla_credits_paid_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost_per_ticket_excl_credits_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    cost_per_ticket_incl_credits_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
