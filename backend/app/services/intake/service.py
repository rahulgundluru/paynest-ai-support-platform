"""Ticket intake from the New ticket screen: the same PII gate, normalization, customer lookup and SLA
engine as the source-data import, applied to one ticket.

- The PII gate runs before anything except the encrypted raw submission is written.
- Ticket ids come from the `app_ticket_seq` sequence (PN-200001 upward), so they never collide with the
  source data (PN-100001..PN-101526), and they keep the PN- format the duplicate rules (D1) understand.
- Tickets are marked `origin='app'`, so the evaluation gates, which measure the source data, exclude them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import Customer, SlaTerm
from app.models.tickets import IngestionBatch, SlaTracking, SourceRecord, Ticket, TicketEvent, TicketMessage
from app.services import audit
from app.services.customer_lookup import CustomerDirectory
from app.services.ingestion.pipeline import IngestionRun, _language_hint, _NormLog
from app.services.normalization import rules
from app.services.normalization.timestamps import IST, in_payroll_window
from app.services.pii import vault
from app.services.pii.gate import PiiGate
from app.services.pipeline.steps import now_utc, step_record
from app.services.sla.engine import RULE_VERSION, SlaTerms, evaluate

APP_SOURCE_FILE = "app:new-ticket"


@dataclass(frozen=True)
class NewTicket:
    channel: str
    customer_id: str | None
    subject: str
    body: str
    priority: str | None = None
    customer_category: str | None = None
    received_at: datetime | None = None


@dataclass
class IntakeResult:
    ticket: Ticket
    steps: list[dict[str, Any]]


async def create_ticket(
    session: AsyncSession, data: NewTicket, *, actor: uuid.UUID, retention_days: int, now: datetime | None = None
) -> IntakeResult:
    now = now or now_utc()
    steps: list[dict[str, Any]] = []

    # 1. Received: id, batch, encrypted raw submission.
    t0 = now_utc()
    seq = int(await session.scalar(text("SELECT nextval('app_ticket_seq')")) or 0)
    external_id = f"PN-{seq}"
    raw = {
        "channel": data.channel, "customer_id": data.customer_id, "priority": data.priority,
        "customer_category": data.customer_category, "subject": data.subject, "body": data.body,
        "received_at": data.received_at.isoformat() if data.received_at else None, "entered_by": str(actor),
    }  # fmt: skip
    raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw_json.encode()).hexdigest()
    batch = IngestionBatch(
        triggered_by=actor, status="completed", finished_at=now,
        summary={"origin": "app", "ticket": external_id, "totals": {"read": 1}},
    )  # fmt: skip
    session.add(batch)
    await session.flush()
    record = SourceRecord(
        batch_id=batch.id, source_file=APP_SOURCE_FILE, source_sha256=digest, record_index=seq, record_hash=digest,
        external_id=external_id, channel=data.channel, status="processing", raw_encrypted=vault.encrypt(raw_json),
    )  # fmt: skip
    session.add(record)
    await session.flush()
    steps.append(
        step_record("received", "done", f"Stored as {external_id} via {data.channel.replace('_', ' ')}",
                    {"external_id": external_id, "channel": data.channel, "raw_encrypted": True}, started=t0)
    )  # fmt: skip

    # 2. PII gate: everything below sees redacted text only.
    t1 = now_utc()
    redaction = PiiGate().redact({"subject": data.subject, "body": data.body})
    helper = IngestionRun(session, Path("."), now, retention_days)
    entity_counts = dict(redaction.entity_counts)
    masked = sum(entity_counts.values())
    steps.append(
        step_record(
            "pii", "done",
            f"{masked} personal value(s) replaced by tokens" if masked else "No personal identifiers found",
            {"masked": masked, "entities": entity_counts, "tokens": sorted(redaction.vault)},
            started=t1,
        )
    )  # fmt: skip

    # 3. Normalization (agent-entered values are already canonical; each still gets a logged rule).
    t2 = now_utc()
    logs: list[_NormLog] = []
    reasons: list[str] = []
    priority = (
        rules.Mapped(data.priority, "PRIORITY_SET_BY_AGENT")
        if data.priority
        else rules.Mapped(None, "PRIORITY_NOT_SET")
    )
    category = (
        rules.Mapped(data.customer_category, "CATEGORY_CUSTOMER_PICK_ENTERED")
        if data.customer_category
        else rules.Mapped(None, "CATEGORY_NOT_GIVEN")
    )
    created_at = data.received_at or now
    created_rule = "CREATED_ENTERED_BY_AGENT" if data.received_at else "CREATED_AT_SUBMISSION"
    logs += [
        _NormLog("priority", data.priority, priority.value, priority.rule),
        _NormLog("customer_category", data.customer_category, category.value, category.rule),
        _NormLog("status", None, "open", "STATUS_NEW_TICKET"),
        _NormLog("created_at", None, created_at.isoformat(), created_rule),
    ]
    if priority.value is None:
        reasons.append("priority_not_set")
    steps.append(
        step_record(
            "normalize", "review" if reasons else "done",
            f"Priority {priority.value or 'not set'}, customer's category {category.value or 'not given'}, "
            f"received {created_at.astimezone(IST).strftime('%d %b %Y %H:%M')} IST",
            {"rules": {e.field: e.rule for e in logs}, "review_reasons": reasons,
             "in_payroll_window": in_payroll_window(created_at)},
            started=t2,
        )
    )  # fmt: skip

    # 4. Customer lookup and SLA.
    t3 = now_utc()
    directory = CustomerDirectory(list(await session.scalars(select(Customer))))
    resolution = directory.resolve(data.channel, data.customer_id, None)
    logs.append(
        _NormLog("customer_id", data.customer_id,
                 resolution.customer.customer_id if resolution.customer else None,
                 f"CUSTOMER_{resolution.method.upper()}")
    )  # fmt: skip
    if resolution.customer is None:
        reasons.append(resolution.reason or "customer_unresolved")
    record.region = resolution.region
    subject_r, body_r = redaction.fields.get("subject"), redaction.fields.get("body")
    ticket = Ticket(
        external_id=external_id,
        source_record_id=record.id,
        channel=data.channel,
        customer_id=resolution.customer.customer_id if resolution.customer else None,
        customer_resolution=resolution.method,
        region=resolution.region,
        region_source=resolution.region_source,
        subject_redacted=subject_r,
        body_redacted=body_r,
        language_hint=_language_hint(body_r),
        priority=priority.value,
        customer_category=category.value,
        status="open",
        created_at=created_at,
        in_payroll_window=in_payroll_window(created_at),
        ingestion_status="requires_review" if reasons else "processed",
        origin="app",
        review_reasons=sorted(set(reasons)),
        attributes={"entered_by": str(actor), "fingerprint": digest},
    )
    session.add(ticket)
    await session.flush()
    detections = helper._store_pii(record, redaction, resolution.region)
    for detection in detections:
        detection.ticket_id = ticket.id
    session.add(TicketMessage(ticket_id=ticket.id, seq=0, author_type="customer", sent_at=created_at,
                              body_redacted=body_r or ""))  # fmt: skip
    session.add(
        TicketEvent(ticket_id=ticket.id, seq=0, event_type="created", occurred_at=created_at, actor="app-entry",
                    data={"category": category.value, "channel": data.channel})
    )  # fmt: skip

    customer = resolution.customer
    term = None
    if customer and priority.value:
        term = await session.scalar(
            select(SlaTerm).where(
                SlaTerm.template_version == "v3.2", SlaTerm.tier == customer.tier, SlaTerm.priority == priority.value
            )
        )
    sla = evaluate(
        tier=customer.tier if customer else None,
        priority=priority.value,
        created_at=created_at,
        first_response_at=None,
        resolved_at=None,
        monthly_fee_usd=customer.monthly_fee_usd if customer else None,
        terms=SlaTerms(term.template_version, term.first_response_h, term.resolution_h, term.credit_pct)
        if term
        else None,
        as_of=now,
    )
    session.add(
        SlaTracking(
            ticket_id=ticket.id, applicable=sla.applicable, not_applicable_reason=sla.not_applicable_reason,
            template_version=sla.template_version, tier=customer.tier if customer else None, priority=priority.value,
            first_response_target_h=sla.first_response_target_h, resolution_target_h=sla.resolution_target_h,
            first_response_due_at=sla.first_response_due_at, resolution_due_at=sla.resolution_due_at,
            first_response_hours=sla.first_response_hours, resolution_hours=sla.resolution_hours,
            first_response_breached=sla.first_response_breached, resolution_breached=sla.resolution_breached,
            severity_multiplier=sla.severity_multiplier, credit_pct=sla.credit_pct, credit_usd=sla.credit_usd,
            rule_version=RULE_VERSION,
        )
    )  # fmt: skip
    helper._store_logs(record, ticket.id, logs)
    record.status, record.status_reasons = ticket.ingestion_status, ticket.review_reasons

    if customer:
        due = sla.resolution_due_at.astimezone(IST).strftime("%d %b %H:%M") if sla.resolution_due_at else None
        summary = f"{customer.name} · {customer.tier} · {customer.region}" + (
            f" · resolve by {due} IST ({sla.resolution_target_h} h target)" if due else " · SLA not applicable"
        )
    else:
        summary = "Customer not verified: no tier, SLA or region-specific answer is possible"
    steps.append(
        step_record(
            "customer_sla", "done" if customer else "review", summary,
            {
                "customer_id": ticket.customer_id, "tier": customer.tier if customer else None,
                "region": ticket.region, "resolution": resolution.method,
                "sla_applicable": sla.applicable, "not_applicable_reason": sla.not_applicable_reason,
                "first_response_target_h": str(sla.first_response_target_h) if sla.first_response_target_h else None,
                "resolution_target_h": str(sla.resolution_target_h) if sla.resolution_target_h else None,
                "resolution_due_at": sla.resolution_due_at.isoformat() if sla.resolution_due_at else None,
                "credit_pct_if_breached": str(term.credit_pct) if term else None,
            },
            started=t3,
        )
    )  # fmt: skip
    await audit.record(
        session, "ticket.created", actor_user_id=actor, entity_type="ticket", entity_id=external_id,
        region=ticket.region, details={"channel": data.channel, "pii_masked": masked, "customer": ticket.customer_id},
    )  # fmt: skip
    return IntakeResult(ticket=ticket, steps=steps)
