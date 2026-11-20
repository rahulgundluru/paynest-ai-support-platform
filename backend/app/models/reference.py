"""Reference data loaded from the source case: customers, agents, SLA terms, Finance breach list."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIERS = ("Enterprise", "Business", "Standard")
REGIONS = ("IN", "UAE")
PRIORITIES = ("P1", "P2", "P3")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(String(12), nullable=False)
    region: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    monthly_fee_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    employees_paid: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str] = mapped_column(String(200), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(_in("tier", TIERS), name="tier"),
        CheckConstraint(_in("region", REGIONS), name="region"),
        CheckConstraint("monthly_fee_usd >= 0", name="fee_non_negative"),
    )


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(String(2), nullable=False)
    desk: Mapped[str] = mapped_column(String(40), nullable=False)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), nullable=False)
    hire_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    left_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("tier IN ('L1', 'L2', 'L3')", name="tier"),
        CheckConstraint("status IN ('active', 'left')", name="status"),
    )


class SlaTerm(Base):
    """Contract Schedule 3 targets (template v3.2). Elapsed calendar hours from ticket creation."""

    __tablename__ = "sla_terms"

    template_version: Mapped[str] = mapped_column(String(8), primary_key=True)
    tier: Mapped[str] = mapped_column(String(12), primary_key=True)
    priority: Mapped[str] = mapped_column(String(2), primary_key=True)
    first_response_h: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    resolution_h: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    credit_pct: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("tier", TIERS), name="tier"),
        CheckConstraint(_in("priority", PRIORITIES), name="priority"),
    )


class FinanceSlaBreach(Base):
    """Finance's own breach and credit list, kept verbatim for reconciliation against the SLA engine."""

    __tablename__ = "finance_sla_breaches"

    breach_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    ticket_external_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(12), nullable=False)
    priority: Mapped[str] = mapped_column(String(2), nullable=False)
    target_h: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False)
    actual_resolution_h: Mapped[Decimal] = mapped_column(Numeric(8, 1), nullable=False)
    credit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    monthly_fee_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    credit_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    invoice_month: Mapped[str] = mapped_column(String(7), nullable=False)
    agent_noted_reason: Mapped[str | None] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(60))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
