"""Duplicate (resubmission) and incident detection. Pure functions over redacted ticket views.

Discovery evidence that shapes these rules:
- All 26 known resubmissions carry an explicit signal: 18 cite the parent ticket id ("Following up on
  my earlier ticket PN-…") and 8 are "RE: <same subject>" + "Second request - …" emails.
- 199 pairs of same-customer, same-text tickets within 7 days are NOT duplicates (template phrasing).
  So text similarity alone never merges tickets; a resubmission needs an explicit follow-up signal.
- Meridian (C-1002), 25 Sep: 30 payslip tickets in one burst. Runbook §9: 5+ reports of one issue
  from one customer = an incident.
Incidents GROUP tickets under one case; each ticket keeps its own channel, messages and history.
Inputs are only what a live system has at intake (customer, time, channel, redacted text, the
customer's category). Resolution events (which contain "duplicate of …") are never used.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

RULESET_VERSION = "dedupe-2026.11.19"
_TICKET_REF = re.compile(r"\bPN-\d{6}\b")
_SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_FOLLOW_UP_BODY = re.compile(
    r"^\s*(second request|following up|follow[- ]up|reminder|gentle reminder)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class TicketView:
    id: str  # internal uuid as string
    external_id: str | None
    customer_id: str | None
    channel: str
    created_at: datetime
    subject: str | None
    body: str | None
    category: str | None


@dataclass(frozen=True)
class ResubmissionLink:
    ticket_id: str
    parent_id: str
    rule_id: str
    reason: str
    confidence: float


@dataclass
class IncidentCandidate:
    customer_id: str
    category: str
    ticket_ids: list[str] = field(default_factory=list)
    first_at: datetime | None = None
    declared_at: datetime | None = None
    rule_id: str = "I1"


@dataclass(frozen=True)
class DedupeConfig:
    follow_up_window: timedelta = timedelta(days=7)
    incident_min_tickets: int = 5
    incident_gap: timedelta = timedelta(hours=3)


def _norm_subject(subject: str | None) -> str:
    return re.sub(r"\s+", " ", _SUBJECT_PREFIX.sub("", subject or "")).strip().casefold()


def has_follow_up_marker(t: TicketView) -> bool:
    return bool(_SUBJECT_PREFIX.match(t.subject or "")) or bool(_FOLLOW_UP_BODY.match(t.body or ""))


def find_resubmissions(tickets: list[TicketView], config: DedupeConfig = DedupeConfig()) -> list[ResubmissionLink]:
    by_external = {t.external_id: t for t in tickets if t.external_id}
    by_customer: dict[str, list[TicketView]] = defaultdict(list)
    for t in sorted(tickets, key=lambda x: x.created_at):
        if t.customer_id:
            by_customer[t.customer_id].append(t)
    links: list[ResubmissionLink] = []
    for t in tickets:
        if not t.customer_id:
            continue  # identity unknown: never link across possibly different customers
        text = f"{t.subject or ''} {t.body or ''}"
        refs = [r for r in _TICKET_REF.findall(text) if r != t.external_id]
        parent = next(
            (
                by_external[r]
                for r in refs
                if r in by_external
                and by_external[r].customer_id == t.customer_id
                and by_external[r].created_at < t.created_at
            ),
            None,
        )
        if parent:
            links.append(ResubmissionLink(t.id, parent.id, "D1", f"Cites earlier ticket {parent.external_id}", 0.99))
            continue
        if not has_follow_up_marker(t):
            continue
        subject = _norm_subject(t.subject)
        if not subject:
            continue
        candidates = [
            p
            for p in by_customer[t.customer_id]
            if p.id != t.id
            and p.created_at < t.created_at
            and t.created_at - p.created_at <= config.follow_up_window
            and _norm_subject(p.subject) == subject
            and not has_follow_up_marker(p)
        ]
        if candidates:
            parent = candidates[-1]  # most recent matching original
            reason = (
                f"Follow-up marker and same subject as {parent.external_id or parent.id} "
                f"({(t.created_at - parent.created_at).total_seconds() / 3600:.1f} h earlier)"
            )
            confidence = 0.9
            if len(candidates) > 1:  # ambiguous: a person should confirm which original it follows
                others = ", ".join(c.external_id or c.id for c in candidates[:-1])
                reason += f"; ambiguous, other possible originals: {others}"
                confidence = 0.6
            links.append(ResubmissionLink(t.id, parent.id, "D2", reason, confidence))
    return links


def find_incidents(
    tickets: list[TicketView], exclude: set[str], config: DedupeConfig = DedupeConfig()
) -> list[IncidentCandidate]:
    """Same customer + same category, chained by gaps <= incident_gap, at least incident_min_tickets."""
    groups: dict[tuple[str, str], list[TicketView]] = defaultdict(list)
    for t in tickets:
        if t.customer_id and t.category and t.id not in exclude:
            groups[(t.customer_id, t.category)].append(t)
    incidents: list[IncidentCandidate] = []
    for (customer, category), items in groups.items():
        items.sort(key=lambda x: x.created_at)
        clusters: list[list[TicketView]] = []
        for t in items:
            if clusters and t.created_at - clusters[-1][-1].created_at <= config.incident_gap:
                clusters[-1].append(t)
            else:
                clusters.append([t])
        for cluster in clusters:
            if len(cluster) >= config.incident_min_tickets:
                incidents.append(
                    IncidentCandidate(
                        customer_id=customer,
                        category=category,
                        ticket_ids=[c.id for c in cluster],
                        first_at=cluster[0].created_at,
                        declared_at=cluster[config.incident_min_tickets - 1].created_at,
                    )
                )
    return incidents
