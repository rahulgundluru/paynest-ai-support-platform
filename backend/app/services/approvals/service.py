"""Human-approval workflow: evidence packs, the review queue, validated drafts and audited decisions.

State machine (persisted; resumable after restarts):
    pending ──edit──► pending (draft re-validated)
    pending ──approve──► approved      (only with a draft that passes every validation check; not for `block`)
    pending ──reject──► rejected       (draft discarded; ticket stays with its queue)
    pending ──escalate──► escalated    (to L2 / L3 engineering / security, with a note)
    pending ──reassign──► pending      (new queue, with a note)
    pending ──resolve──► resolved      (closed without an outbound reply, with a note)
Only `pending` items accept actions. No action moves money or changes payroll data: the platform
has no such capability, and drafts that promise it fail validation.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approvals import Approval, ApprovalEvent, LearnedMemory
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentVersion, StatutoryRule
from app.models.processing import Classification, Incident, IncidentLink, RoutingDecision
from app.models.reference import Customer
from app.models.tickets import PiiDetection, SlaTracking, Ticket
from app.services import audit
from app.services.classification.service import injection_signals
from app.services.knowledge.retrieval import retrieve, statutory_rates
from app.services.normalization.timestamps import IST
from app.services.validation.output import DocValidity, RuleFacts, ValidationContext, validate_draft

ESCALATION_TARGETS = {
    "L2": "Payroll-Ops",
    "L3": "Engineering-L3",
    "SECURITY": "Security-Review",
    "DPO": "Security-Review",
}
REVIEW_RULES = {"R1", "R2", "R5", "R6", "R7"}


class WorkflowError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def ticket_date(ticket: Ticket) -> date:
    return ticket.created_at.astimezone(IST).date()


async def build_evidence(session: AsyncSession, ticket: Ticket, decision: RoutingDecision | None) -> dict[str, Any]:
    customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
    sla = await session.get(SlaTracking, ticket.id)
    classification = await session.scalar(
        select(Classification)
        .where(Classification.ticket_id == ticket.id)
        .order_by(Classification.created_at.desc())
        .limit(1)
    )
    incidents = (
        await session.execute(
            select(Incident.kind, Incident.owner_queue, Incident.master_ticket_id, IncidentLink.role)
            .join(IncidentLink, IncidentLink.incident_id == Incident.id)
            .where(IncidentLink.ticket_id == ticket.id, IncidentLink.active)
        )
    ).all()
    tokens = sorted(
        {d.token for d in await session.scalars(select(PiiDetection).where(PiiDetection.ticket_id == ticket.id))}
    )
    day = ticket_date(ticket)
    knowledge: list[dict[str, Any]] = []
    rates: list[dict[str, Any]] = []
    if ticket.region:
        _, hits = await retrieve(
            session, f"{ticket.subject_redacted or ''} {ticket.body_redacted or ''}", region=ticket.region, as_of=day,
            limit=3, ticket_id=ticket.id,
        )  # fmt: skip
        knowledge = [
            {
                "document_id": h.document_id, "version": h.version, "title": h.title, "excerpt": h.text[:400],
                "content_complete": h.content_complete,
                "effective_from": h.effective_from.isoformat() if h.effective_from else None,
                "effective_to": h.effective_to.isoformat() if h.effective_to else None,
            }
            for h in hits
        ]  # fmt: skip
        rates = [
            {"rule_id": r.rule_id, "title": r.title, "value": r.value}
            for r in await statutory_rates(session, ticket.region, day)
        ]
    who = f"{customer.tier} customer {customer.name} ({customer.region})" if customer else "An unverified customer"
    summary = (
        f"{who} raised a {ticket.priority or 'un-prioritised'} "
        f"{(ticket.customer_category or 'uncategorised').replace('_', ' ')} ticket via {ticket.channel.replace('_', ' ')} "
        f'on {ticket.created_at.astimezone(IST).strftime("%d %b %Y %H:%M")} IST: "{(ticket.subject_redacted or ticket.body_redacted or "")[:140]}".'
    )
    return {
        "summary": summary,
        "ticket": {
            "external_id": ticket.external_id, "channel": ticket.channel, "priority": ticket.priority,
            "customer_category": ticket.customer_category, "created_at": ticket.created_at.isoformat(),
            "ticket_date": day.isoformat(), "language_hint": ticket.language_hint,
        },
        "customer": (
            {"id": customer.customer_id, "name": customer.name, "tier": customer.tier, "region": customer.region}
            if customer else None
        ),
        "sla": (
            {
                "applicable": sla.applicable, "resolution_target_h": str(sla.resolution_target_h or ""),
                "resolution_due_at": sla.resolution_due_at.isoformat() if sla.resolution_due_at else None,
                "resolution_breached": sla.resolution_breached, "credit_usd": str(sla.credit_usd or ""),
                "not_applicable_reason": sla.not_applicable_reason,
            }
            if sla else None
        ),
        "classification": (
            {"status": classification.status, "category": classification.category, "confidence": classification.confidence}
            if classification else None
        ),
        "routing": (
            {"lane": decision.lane, "queue": decision.queue, "rule_id": decision.rule_id, "reason": decision.reason}
            if decision else None
        ),
        "incidents": [{"kind": k, "owner_queue": q, "role": r} for k, q, _, r in incidents],
        "knowledge_in_force": knowledge,
        "statutory_rates_in_force": rates,
        "pii_tokens": tokens,
        "injection_signals": injection_signals(ticket.subject_redacted, ticket.body_redacted),
        "suggested_response": None,
        "suggested_response_note": "No drafting model is configured; the reviewer writes the reply.",
    }  # fmt: skip


async def validation_context(session: AsyncSession, ticket: Ticket, statutory: bool) -> ValidationContext:
    customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
    names = list(await session.scalars(select(Customer.name)))
    windows: dict[str, list[DocValidity]] = {}
    for doc_id, start, end in (
        await session.execute(
            select(KnowledgeDocument.id, KnowledgeDocumentVersion.effective_from, KnowledgeDocumentVersion.effective_to)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "active", KnowledgeDocumentVersion.approval_status == "approved")
        )
    ).all():
        windows.setdefault(doc_id, []).append(DocValidity(start, end))
    rules = [
        RuleFacts(r.rule_id, r.region, r.effective_from, r.old_value, r.new_value)
        for r in await session.scalars(select(StatutoryRule))
    ]
    tokens = {
        d.token.strip("<>")
        for d in await session.scalars(select(PiiDetection).where(PiiDetection.ticket_id == ticket.id))
    }
    return ValidationContext(
        ticket_date=ticket_date(ticket),
        region=ticket.region,
        category=ticket.customer_category,
        customer_name=customer.name if customer else None,
        other_customer_names=[n for n in names if not customer or n != customer.name],
        ticket_tokens=tokens,
        rules=rules,
        documents=windows,
        statutory_answer=statutory,
    )


async def open_review(session: AsyncSession, ticket: Ticket, decision: RoutingDecision) -> Approval | None:
    """Creates a pending review item when the routing decision requires a person. Idempotent per ticket."""
    if not decision.requires_approval or decision.rule_id not in REVIEW_RULES:
        return None
    existing = await session.scalar(
        select(Approval).where(Approval.ticket_id == ticket.id, Approval.status == "pending")
    )
    if existing:
        return existing
    approval = Approval(
        ticket_id=ticket.id,
        routing_decision_id=decision.id,
        region=ticket.region,
        lane=decision.lane,
        queue=decision.queue,
        rule_id=decision.rule_id,
        escalation_reason=decision.reason,
        evidence=await build_evidence(session, ticket, decision),
        events=[ApprovalEvent(action="created", to_status="pending", details={"rule": decision.rule_id})],
    )
    session.add(approval)
    return approval


async def build_review_queue(session: AsyncSession) -> dict[str, int]:
    latest: dict[uuid.UUID, RoutingDecision] = {}
    for d in await session.scalars(select(RoutingDecision).order_by(RoutingDecision.id)):
        latest[d.ticket_id] = d
    created = 0
    for ticket_id, decision in latest.items():
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None:
            continue
        before = await session.scalar(select(Approval.id).where(Approval.ticket_id == ticket_id))
        if await open_review(session, ticket, decision) is not None and before is None:
            created += 1
    await session.commit()
    return {"review_items_created": created}


def _transition(
    approval: Approval, action: str, to_status: str, actor: uuid.UUID, note: str | None, **details: Any
) -> None:
    if approval.status != "pending":
        raise WorkflowError(409, f"Review item is already {approval.status}")
    approval.events.append(
        ApprovalEvent(
            actor_user_id=actor,
            action=action,
            from_status=approval.status,
            to_status=to_status,
            note=note,
            details=details,
        )
    )
    approval.status = to_status
    if to_status != "pending":
        approval.decided_by, approval.decided_at = actor, datetime.now(tz=UTC)


async def edit_draft(
    session: AsyncSession, approval: Approval, ticket: Ticket, text: str, actor: uuid.UUID
) -> Approval:
    if approval.status != "pending":
        raise WorkflowError(409, f"Review item is already {approval.status}")
    report = validate_draft(text, await validation_context(session, ticket, statutory=approval.rule_id == "R7"))
    approval.draft_text, approval.draft_source, approval.validation = text, "human", report.as_dict()
    approval.events.append(
        ApprovalEvent(actor_user_id=actor, action="edited", from_status="pending", to_status="pending",
                      details={"validation_passed": report.passed})
    )  # fmt: skip
    await audit.record(session, "approval.edited", actor_user_id=actor, entity_type="approval", entity_id=str(approval.id),
                       region=approval.region, details={"validation_passed": report.passed})  # fmt: skip
    return approval


async def decide(
    session: AsyncSession, approval: Approval, ticket: Ticket, action: str, actor: uuid.UUID,
    note: str | None = None, target: str | None = None,
) -> Approval:  # fmt: skip
    if action == "approve":
        if approval.lane == "block":
            raise WorkflowError(409, "Blocked tickets cannot be approved for sending; resolve or escalate them")
        if not approval.draft_text:
            raise WorkflowError(409, "There is no draft to approve")
        report = validate_draft(
            approval.draft_text, await validation_context(session, ticket, statutory=approval.rule_id == "R7")
        )
        approval.validation = report.as_dict()
        if not report.passed:
            failed = [c.name for c in report.checks if not c.passed]
            raise WorkflowError(422, f"Draft fails validation: {', '.join(failed)}")
        _transition(approval, "approved", "approved", actor, note)
        await _remember(session, approval, ticket, actor)
    elif action == "reject":
        _transition(approval, "rejected", "rejected", actor, note)
    elif action == "escalate":
        if target not in ESCALATION_TARGETS:
            raise WorkflowError(422, f"Escalation target must be one of {sorted(ESCALATION_TARGETS)}")
        queue = ESCALATION_TARGETS[target]
        _transition(approval, "escalated", "escalated", actor, note, target=target, queue=queue)
        approval.queue = queue
    elif action == "reassign":
        if not target or not re.fullmatch(r"[A-Za-z0-9-]{2,40}", target):
            raise WorkflowError(422, "A target queue is required")
        _transition(approval, "reassigned", "pending", actor, note, from_queue=approval.queue, to_queue=target)
        approval.queue = target
    elif action == "resolve":
        if not note:
            raise WorkflowError(422, "A resolution note is required")
        _transition(approval, "resolved", "resolved", actor, note)
    else:
        raise WorkflowError(422, f"Unknown action {action}")
    await audit.record(
        session, f"approval.{action}", actor_user_id=actor, entity_type="approval", entity_id=str(approval.id),
        region=approval.region, details={"ticket": ticket.external_id, "rule": approval.rule_id, "target": target},
    )  # fmt: skip
    return approval


async def _remember(session: AsyncSession, approval: Approval, ticket: Ticket, actor: uuid.UUID) -> None:
    """Learned memory from a HUMAN-approved reply only. Expires when a cited policy version stops being in force."""
    day = ticket_date(ticket)
    cited = sorted(set(re.findall(r"\b(KB-\d{4}|R-[A-Z]{2,3}-[A-Z]+-\d{4}-\d{2})\b", approval.draft_text or "")))
    versions: list[dict[str, Any]] = []
    expiries: list[date] = []
    for doc_id in cited:
        for v in await session.scalars(
            select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == doc_id)
        ):
            if (v.effective_from is None or v.effective_from <= day) and (
                v.effective_to is None or v.effective_to >= day
            ):
                versions.append({"document_id": doc_id, "version": v.version})
                if v.effective_to:
                    expiries.append(v.effective_to)
    session.add(
        LearnedMemory(
            approval_id=approval.id,
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            region=ticket.region,
            category=ticket.customer_category,
            resolution_text=approval.draft_text or "",
            cited_versions=versions,
            valid_until=min(expiries) if expiries else None,
            approved_by=actor,
        )
    )
