"""Loads reference data (customers, agents, Finance breach list) from the source mirror. Idempotent upserts."""

from __future__ import annotations

import asyncio
import csv
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import Agent, Customer, FinanceSlaBreach

CUSTOMERS_FILE = "data-room/data/customers.csv"
AGENTS_FILE = "data-room/data/agent_roster.csv"
BREACHES_FILE = "data-room/data/sla_breaches_q3.csv"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _read_sources(source_dir: Path) -> tuple[str, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    return (
        sha256_file(source_dir / CUSTOMERS_FILE),
        _rows(source_dir / CUSTOMERS_FILE),
        _rows(source_dir / AGENTS_FILE),
        _rows(source_dir / BREACHES_FILE),
    )


async def load_reference(session: AsyncSession, source_dir: Path) -> dict[str, int]:
    sha, customer_rows, agent_rows, breach_rows = await asyncio.to_thread(_read_sources, source_dir)
    customers = [
        {
            "customer_id": r["customer_id"],
            "name": r["name"],
            "tier": r["tier"],
            "region": r["region"],
            "monthly_fee_usd": Decimal(r["monthly_fee_usd"]),
            "employees_paid": int(r["employees_paid"]) if r["employees_paid"] else None,
            "source_file": CUSTOMERS_FILE,
            "source_sha256": sha,
        }
        for r in customer_rows
    ]
    stmt = insert(Customer).values(customers)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Customer.customer_id],
            set_={k: stmt.excluded[k] for k in customers[0] if k != "customer_id"},
        )
    )

    agents = [
        {
            "agent_id": r["agent_id"],
            "name": r["name"],
            "tier": r["tier"],
            "desk": r["desk"],
            "languages": [lang.strip() for lang in r["languages"].split(",") if lang.strip()],
            "hire_date": _date(r["hire_date"]),
            "status": r["status"],
            "left_date": _date(r["left_date"]),
        }
        for r in agent_rows
    ]
    stmt_a = insert(Agent).values(agents)
    await session.execute(
        stmt_a.on_conflict_do_update(
            index_elements=[Agent.agent_id], set_={k: stmt_a.excluded[k] for k in agents[0] if k != "agent_id"}
        )
    )

    breaches = [
        {
            "breach_id": r["breach_id"],
            "ticket_external_id": r["ticket_id"],
            "customer_id": r["customer_id"],
            "tier": r["tier"],
            "priority": r["priority"],
            "target_h": Decimal(r["sla_resolution_target_h"]),
            "actual_resolution_h": Decimal(r["actual_resolution_h"]),
            "credit_pct": Decimal(r["credit_pct"]),
            "monthly_fee_usd": Decimal(r["monthly_fee_usd"]),
            "credit_usd": Decimal(r["credit_usd"]),
            "invoice_month": r["invoice_month"],
            "agent_noted_reason": r["agent_noted_reason"] or None,
            "approved_by": r["approved_by"] or None,
        }
        for r in breach_rows
    ]
    stmt_b = insert(FinanceSlaBreach).values(breaches)
    await session.execute(
        stmt_b.on_conflict_do_update(
            index_elements=[FinanceSlaBreach.breach_id],
            set_={k: stmt_b.excluded[k] for k in breaches[0] if k != "breach_id"},
        )
    )
    return {"customers": len(customers), "agents": len(agents), "finance_breaches": len(breaches)}
