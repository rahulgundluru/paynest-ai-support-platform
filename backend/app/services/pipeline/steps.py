"""The pipeline's steps, in order, and the record kept for each one in `pipeline_runs.steps`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

STEP_DEFS: tuple[tuple[str, str, str], ...] = (
    ("received", "Ticket received", "Stored with a new PN- id; the raw submission is encrypted."),
    ("pii", "PII gate", "Personal identifiers are replaced by tokens before anything else sees the text."),
    ("normalize", "Normalize", "Priority, category, status and time mapped to one schema, each with its rule."),
    ("customer_sla", "Customer + SLA", "Customer, tier and region resolved; SLA clock and credit exposure computed."),
    ("duplicates", "Duplicates & incidents", "Follow-ups (D1/D2) and multi-ticket incidents (I1) for this customer."),
    ("injection", "Injection screen", "Rule-based check for instructions aimed at an AI (defence in depth)."),
    ("classify", "AI classification", "The model returns typed signals: category, priority, confidence."),
    ("routing", "Routing rules", "Rules R1–R9 decide lane, queue, level and approval. The model never routes."),
    ("retrieval", "Date-aware retrieval", "Knowledge and statutory rules in force on the ticket date."),
    ("draft", "AI draft", "The model drafts a cited reply for a person to review, when the lane allows it."),
    ("validation", "Output validation", "Deterministic checks: PII, money promises, stale values, citations."),
    ("review", "Human review", "A person approves, edits or escalates. The AI never approves."),
)
STEP_KEYS = [k for k, _, _ in STEP_DEFS]
INTAKE_KEYS = ("received", "pii", "normalize", "customer_sla")


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def blank_steps() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": label,
            "description": description,
            "status": "pending",
            "summary": None,
            "details": {},
            "started_at": None,
            "duration_ms": None,
            "cost_usd": None,
        }
        for key, label, description in STEP_DEFS
    ]


def step_record(
    key: str,
    status: str,
    summary: str,
    details: dict[str, Any] | None = None,
    *,
    started: datetime,
    finished: datetime | None = None,
    cost_usd: Decimal | None = None,
) -> dict[str, Any]:
    finished = finished or now_utc()
    return {
        "key": key,
        "status": status,
        "summary": summary,
        "details": details or {},
        "started_at": started.isoformat(),
        "duration_ms": max(0, int((finished - started).total_seconds() * 1000)),
        "cost_usd": str(cost_usd) if cost_usd is not None else None,
    }


def merge(steps: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns a new list (JSONB change detection needs a new object) with one step updated."""
    out = []
    for s in steps:
        out.append({**s, **record} if s["key"] == record["key"] else dict(s))
    return out
