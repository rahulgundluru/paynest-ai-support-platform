"""Versioned normalization rules. Every mapping here is traceable to evidence in the source data.

Evidence (docs/discovery/README.md):
- Priority crosswalk verified against each ticket's `created` event: urgent/high/normal -> P1/P2/P3
  (widget) and S1/S2/S3 -> P1/P2/P3 (partner portal), with zero contradictions.
- Category labels: the 35 spellings found in the export, mapped to the nine dropdown categories of
  the triage SOP (data-room/process/ticket_triage_sop.md). Unknown labels are NOT guessed.
- Queues: triage SOP category -> queue table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULESET_VERSION = "norm-2026.11.19"


@dataclass(frozen=True)
class Mapped:
    value: str | None
    rule: str


def _key(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


CATEGORY_LABELS: dict[str, str] = {
    # how_to
    "how-to": "how_to", "how_to": "how_to", "howto": "how_to", "how to": "how_to",
    # payroll
    "payroll": "payroll", "payroll-run": "payroll", "payroll run": "payroll", "payroll issue": "payroll",
    # statutory
    "statutory": "statutory", "statutory/compliance": "statutory", "compliance - pf/wps": "statutory",
    # reports
    "reports": "reports", "report / export": "reports",
    # leave & attendance
    "leave": "leave_attendance", "leave-attendance": "leave_attendance",
    "leave & attendance": "leave_attendance", "leave/attendance": "leave_attendance",
    # integration
    "integration": "integration", "integrations": "integration",
    "api / integration": "integration", "integration bug": "integration",
    # billing
    "billing": "billing", "billing & invoices": "billing",
    # access / login
    "access": "access_login", "access / login": "access_login", "access-login": "access_login",
    "login issue": "access_login",
    # onboarding
    "onboarding": "onboarding", "new customer setup": "onboarding",
}  # fmt: skip

CATEGORY_QUEUE: dict[str, str] = {
    "payroll": "Payroll-Ops",
    "statutory": "Statutory-Compliance",
    "how_to": "General-L1",
    "reports": "Reports-Analytics",
    "leave_attendance": "Leave-Attendance",
    "integration": "Integrations",
    "billing": "Billing",
    "access_login": "Access-Support",
    "onboarding": "Onboarding",
}
QUEUE_CATEGORY = {queue: category for category, queue in CATEGORY_QUEUE.items()}

PRIORITY_BY_CHANNEL: dict[str, dict[str, str]] = {
    "email": {"P1": "P1", "P2": "P2", "P3": "P3"},
    "widget": {"urgent": "P1", "high": "P2", "normal": "P3"},
    "partner_portal": {"S1": "P1", "S2": "P2", "S3": "P3"},
}

STATUS_LABELS: dict[str, str] = {"closed": "closed", "resolved": "resolved", "solved": "resolved", "open": "open"}


def map_category(label: str | None) -> Mapped:
    if label is None or not label.strip():
        return Mapped(None, "CATEGORY_MISSING")
    category = CATEGORY_LABELS.get(_key(label))
    return Mapped(category, "CATEGORY_LABEL_MAP" if category else "CATEGORY_UNKNOWN_LABEL")


def map_priority(channel: str, raw: str | None) -> Mapped:
    if raw is None or not str(raw).strip():
        return Mapped(None, "PRIORITY_MISSING")
    value = PRIORITY_BY_CHANNEL.get(channel, {}).get(str(raw).strip())
    return Mapped(value, f"PRIORITY_{channel.upper()}_MAP" if value else "PRIORITY_UNKNOWN_VALUE")


def map_status(raw: str | None) -> Mapped:
    if raw is None:
        return Mapped(None, "STATUS_MISSING")
    value = STATUS_LABELS.get(_key(raw))
    return Mapped(value, "STATUS_LABEL_MAP" if value else "STATUS_UNKNOWN_VALUE")


def category_for_queue(queue: str | None) -> str | None:
    return QUEUE_CATEGORY.get(queue) if queue else None
