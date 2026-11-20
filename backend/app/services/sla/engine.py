"""SLA calculation engine (pure functions, no I/O).

Contract basis: data-room/process/sla_contract_excerpt.md, template v3.2.
- Targets are ELAPSED CALENDAR HOURS from ticket creation (§3.1 note), not business hours.
- Resolution time runs to the FINAL resolved event; reopened time counts (§3.3).
- Credit = credit % of the monthly subscription fee per breached ticket; x1.5 if the actual
  resolution time exceeds twice the target (§3.4). No monthly cap under v3.2.
- Credits apply to resolution misses only; first-response targets carry no credit.
- Standard tier is best effort: no targets, no credits.
- §3.5 exclusion ("Pending - customer" intervals) cannot be applied: no such status exists in any
  source system export. Recorded as a known limitation, not silently ignored.
Validated against Finance's breach list: every one of the 128 credits is reproduced (see tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

RULE_VERSION = "sla-v3.2-r1"
SEVERITY_MULTIPLIER = Decimal("1.5")


@dataclass(frozen=True)
class SlaTerms:
    template_version: str
    first_response_h: Decimal
    resolution_h: Decimal
    credit_pct: Decimal


@dataclass(frozen=True)
class SlaResult:
    applicable: bool
    not_applicable_reason: str | None = None
    template_version: str | None = None
    first_response_target_h: Decimal | None = None
    resolution_target_h: Decimal | None = None
    first_response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    first_response_hours: Decimal | None = None
    resolution_hours: Decimal | None = None
    first_response_breached: bool | None = None
    resolution_breached: bool | None = None
    resolution_remaining_hours: Decimal | None = None
    severity_multiplier: Decimal | None = None
    credit_pct: Decimal | None = None
    credit_usd: Decimal | None = None


def _hours(delta: timedelta) -> Decimal:
    return Decimal(str(delta.total_seconds())) / Decimal(3600)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def evaluate(
    *,
    tier: str | None,
    priority: str | None,
    created_at: datetime,
    first_response_at: datetime | None,
    resolved_at: datetime | None,
    monthly_fee_usd: Decimal | None,
    terms: SlaTerms | None,
    as_of: datetime,
) -> SlaResult:
    if tier is None:
        return SlaResult(False, "customer_unresolved")
    if tier == "Standard":
        return SlaResult(False, "standard_tier_best_effort")
    if priority is None:
        return SlaResult(False, "priority_missing")
    if terms is None:
        return SlaResult(False, "no_sla_terms_for_tier_priority")

    fr_due = created_at + timedelta(hours=float(terms.first_response_h))
    res_due = created_at + timedelta(hours=float(terms.resolution_h))

    fr_hours = _hours(first_response_at - created_at) if first_response_at else None
    if first_response_at is not None:
        fr_breached: bool | None = first_response_at > fr_due
    elif resolved_at is None:
        fr_breached = as_of > fr_due  # still waiting for a first response
    else:
        fr_breached = None  # closed with no recorded first response: unknown

    res_hours = _hours(resolved_at - created_at) if resolved_at else None
    remaining = None if resolved_at else _hours(res_due - as_of)
    res_breached = (resolved_at > res_due) if resolved_at else (as_of > res_due)

    multiplier = credit_pct = credit_usd = None
    # Credits are computed only on the final resolution (an open ticket's exposure is not yet a credit).
    if resolved_at is not None and res_breached and res_hours is not None:
        multiplier = SEVERITY_MULTIPLIER if res_hours > 2 * terms.resolution_h else Decimal("1.0")
        credit_pct = terms.credit_pct * multiplier
        if monthly_fee_usd is not None:
            credit_usd = _q2(monthly_fee_usd * credit_pct / Decimal(100))

    return SlaResult(
        applicable=True,
        template_version=terms.template_version,
        first_response_target_h=terms.first_response_h,
        resolution_target_h=terms.resolution_h,
        first_response_due_at=fr_due,
        resolution_due_at=res_due,
        first_response_hours=_q2(fr_hours) if fr_hours is not None else None,
        resolution_hours=_q2(res_hours) if res_hours is not None else None,
        first_response_breached=fr_breached,
        resolution_breached=res_breached,
        resolution_remaining_hours=_q2(remaining) if remaining is not None else None,
        severity_multiplier=multiplier,
        credit_pct=credit_pct,
        credit_usd=credit_usd,
    )
