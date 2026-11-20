"""Processing monitor: the status of every pipeline stage, derived from what was actually stored."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.api.v1.processing_ai import _ticket
from app.core.rbac import Permission
from app.models.approvals import Approval
from app.models.knowledge import RetrievalLog
from app.models.processing import Classification, IncidentLink, ModelUsage, RoutingDecision
from app.models.tickets import NormalizationLog, PiiDetection, SourceRecord, Ticket

router = APIRouter(prefix="/processing", tags=["processing"])
Monitor = Annotated[Principal, Depends(require(Permission.TICKETS_READ))]


def _stage(name: str, status: str, detail: str) -> dict[str, str]:
    return {"stage": name, "status": status, "detail": detail}


def _classification_status(c: Classification | None) -> str:
    if c is None:
        return "not_run"
    return {"ok": "done", "unavailable": "unavailable"}.get(c.status, "failed")


@router.get("/overview")
async def processing_overview(session: SessionDep, principal: Monitor) -> dict[str, Any]:
    """Counts per pipeline stage across all tickets in the caller's regions."""
    scope = region_filter(principal, Ticket.region)
    total = await session.scalar(select(func.count()).select_from(Ticket).where(scope)) or 0

    async def tickets_with(column: Any, *where: Any) -> int:
        stmt = select(func.count(distinct(column))).join(Ticket, Ticket.id == column).where(scope, *where)
        return await session.scalar(stmt) or 0

    async def grouped(stmt: Any) -> dict[str, int]:
        return {str(k): int(v) for k, v in (await session.execute(stmt)).all()}

    records = await grouped(select(SourceRecord.status, func.count()).group_by(SourceRecord.status))
    ingestion = await grouped(
        select(Ticket.ingestion_status, func.count()).where(scope).group_by(Ticket.ingestion_status)
    )
    resolution = await grouped(
        select(Ticket.customer_resolution, func.count()).where(scope).group_by(Ticket.customer_resolution)
    )
    classifications = await grouped(
        select(Classification.status, func.count(distinct(Classification.ticket_id)))
        .join(Ticket, Ticket.id == Classification.ticket_id)
        .where(scope)
        .group_by(Classification.status)
    )
    approvals = await grouped(
        select(Approval.status, func.count()).where(region_filter(principal, Approval.region)).group_by(Approval.status)
    )
    return {
        "tickets": total,
        "stages": [
            {"stage": "ingestion", "counts": records},
            {"stage": "pii_redaction", "counts": {"tickets_with_pii": await tickets_with(PiiDetection.ticket_id)}},
            {"stage": "normalization", "counts": ingestion},
            {"stage": "customer_lookup", "counts": resolution},
            {
                "stage": "classification",
                "counts": {**classifications, "not_run": total - sum(classifications.values())},
            },
            {
                "stage": "deduplication",
                "counts": {"tickets_in_cases": await tickets_with(IncidentLink.ticket_id, IncidentLink.active)},
            },
            {"stage": "routing", "counts": {"routed": await tickets_with(RoutingDecision.ticket_id)}},
            {"stage": "retrieval", "counts": {"tickets_with_retrieval": await tickets_with(RetrievalLog.ticket_id)}},
            {
                "stage": "answer_generation",
                "counts": {
                    "ai_drafts": await tickets_with(
                        ModelUsage.ticket_id, ModelUsage.operation == "draft", ModelUsage.success
                    ),
                    "no_ai_draft": total
                    - await tickets_with(ModelUsage.ticket_id, ModelUsage.operation == "draft", ModelUsage.success),
                },
                "note": "AI drafts are written only in lanes the routing rules allow, and only when AI is on.",
            },
            {"stage": "human_approval", "counts": approvals},
        ],
    }


@router.get("/{ref}/status")
async def processing_status(ref: str, session: SessionDep, principal: Monitor) -> dict[str, Any]:
    ticket = await _ticket(session, principal, ref)
    record = await session.get(SourceRecord, ticket.source_record_id)
    pii_values, pii_types = (
        await session.execute(
            select(func.count(), func.count(distinct(PiiDetection.entity_type))).where(
                PiiDetection.ticket_id == ticket.id
            )
        )
    ).one()
    norm = await session.scalar(select(func.count()).where(NormalizationLog.ticket_id == ticket.id))
    classification = await session.scalar(
        select(Classification)
        .where(Classification.ticket_id == ticket.id)
        .order_by(Classification.created_at.desc())
        .limit(1)
    )
    links = await session.scalar(select(func.count()).where(IncidentLink.ticket_id == ticket.id, IncidentLink.active))
    decision = await session.scalar(
        select(RoutingDecision)
        .where(RoutingDecision.ticket_id == ticket.id)
        .order_by(RoutingDecision.id.desc())
        .limit(1)
    )
    retrievals = await session.scalar(select(func.count()).where(RetrievalLog.ticket_id == ticket.id))
    approval = await session.scalar(
        select(Approval).where(Approval.ticket_id == ticket.id).order_by(Approval.created_at.desc()).limit(1)
    )
    validation = approval.validation if approval else None
    draft_ok = await session.scalar(
        select(ModelUsage)
        .where(ModelUsage.ticket_id == ticket.id, ModelUsage.operation == "draft", ModelUsage.success)
        .order_by(ModelUsage.created_at.desc())
        .limit(1)
    )
    draft_tried = await session.scalar(
        select(func.count()).where(ModelUsage.ticket_id == ticket.id, ModelUsage.operation == "draft")
    )
    reasons = ", ".join(ticket.review_reasons)
    stages = [
        _stage(
            "ingestion",
            "done" if record else "missing",
            f"{record.source_file} #{record.record_index}" if record else "-",
        ),
        _stage(
            "pii_redaction", "done", f"{pii_values} values masked ({pii_types} types)" if pii_values else "no PII found"
        ),
        _stage(
            "normalization",
            "review" if reasons else "done",
            f"{norm} fields logged" + (f"; review: {reasons}" if reasons else ""),
        ),
        _stage(
            "customer_lookup",
            "done" if ticket.customer_id else "review",
            f"{ticket.customer_id} via {ticket.customer_resolution}" if ticket.customer_id else "customer not verified",
        ),
        _stage(
            "classification",
            _classification_status(classification),
            f"{classification.status} ({classification.provider})" if classification else "not run yet",
        ),
        _stage("deduplication", "done", f"in {links} case(s)" if links else "not part of a case"),
        _stage(
            "routing",
            "done" if decision else "not_run",
            f"{decision.lane} -> {decision.queue} ({decision.rule_id})" if decision else "not routed yet",
        ),
        _stage(
            "retrieval",
            "done" if retrievals else "not_run",
            f"{retrievals} retrieval(s) logged" if retrievals else "none yet",
        ),
        _stage(
            "answer_generation",
            "done"
            if draft_ok
            else (
                "failed"
                if draft_tried
                else ("not_run" if approval is None or approval.draft_source == "none" else "done")
            ),
            f"AI draft by {draft_ok.model}"
            if draft_ok
            else (
                "AI draft attempted but failed"
                if draft_tried
                else (
                    "written by a person"
                    if approval and approval.draft_source == "human"
                    else "no AI draft (lane, switch or cap)"
                )
            ),
        ),
        _stage(
            "validation",
            "not_run" if not validation else ("done" if validation.get("passed") else "failed"),
            "no draft yet"
            if not validation
            else ("draft passed every check" if validation.get("passed") else "draft failed checks"),
        ),
        _stage(
            "human_approval",
            "not_required" if approval is None else ("pending" if approval.status == "pending" else "done"),
            "routing did not require a person" if approval is None else f"{approval.status} ({approval.rule_id})",
        ),
    ]
    return {"ticket": ticket.external_id or str(ticket.id), "stages": stages}
