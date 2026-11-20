"""Per-ticket AI processing: classify (if a model is configured) then route deterministically."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.providers.factory import classifier_provider
from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.api.scoping import region_filter
from app.api.v1.duplicates import incident_out
from app.core.rbac import Permission
from app.models.processing import Classification, Incident, IncidentLink, RoutingDecision
from app.models.tickets import Ticket
from app.schemas.processing import ClassificationOut, ProcessResult, RoutingOut, TicketRouting
from app.services import ai_config, audit
from app.services.approvals.service import open_review
from app.services.classification.service import classify_ticket, injection_signals
from app.services.routing.service import route_ticket
from app.services.runtime_config import load_runtime_config

router = APIRouter(tags=["processing"])


async def _ticket(session: SessionDep, principal: Principal, ref: str) -> Ticket:
    condition = Ticket.external_id == ref
    try:
        condition = condition | (Ticket.id == uuid.UUID(ref))
    except ValueError:
        pass
    ticket = await session.scalar(select(Ticket).where(condition, region_filter(principal, Ticket.region)))
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.post("/tickets/{ref}/process", response_model=ProcessResult)
async def process_ticket(
    ref: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(Permission.TICKETS_PROCESS))],
) -> ProcessResult:
    ticket = await _ticket(session, principal, ref)
    routing_config, _ = await load_runtime_config(session)
    provider, reason = classifier_provider(settings), "no model provider configured"
    if settings.llm_provider == "openrouter":  # model, switch and caps come from AI management
        cfg = await ai_config.load(session, settings)
        provider = None
        if not (cfg.ready and cfg.classifier_model):
            reason = "AI is off or no classification model is selected (AI management)"
        elif injection_signals(ticket.subject_redacted, ticket.body_redacted):
            reason = "injection screen: model not called"
        elif blocked := await ai_config.budget_block(session, cfg, ticket.id, datetime.now(tz=UTC)):
            reason = blocked
        else:
            provider = ai_config.build_provider(settings, cfg.classifier_model)
    classification = await classify_ticket(
        session, ticket, provider, settings, routing_config.confidence_threshold, unavailable_reason=reason
    )
    await session.flush()
    decision = await route_ticket(session, ticket, routing_config)
    await session.flush()
    await open_review(session, ticket, decision)
    await audit.record(
        session, "ticket.processed", actor_user_id=principal.user.id, entity_type="ticket",
        entity_id=ticket.external_id or str(ticket.id), region=ticket.region,
        details={"classification": classification.status, "lane": decision.lane, "rule": decision.rule_id},
    )  # fmt: skip
    await session.commit()
    return ProcessResult(
        classification=ClassificationOut.model_validate(classification), routing=RoutingOut.model_validate(decision)
    )


@router.get("/tickets/{ref}/routing", response_model=TicketRouting)
async def ticket_routing(
    ref: str, session: SessionDep, principal: Annotated[Principal, Depends(require(Permission.TICKETS_READ))]
) -> TicketRouting:
    ticket = await _ticket(session, principal, ref)
    classification = await session.scalar(
        select(Classification)
        .where(Classification.ticket_id == ticket.id)
        .order_by(Classification.created_at.desc())
        .limit(1)
    )
    decision = await session.scalar(
        select(RoutingDecision)
        .where(RoutingDecision.ticket_id == ticket.id)
        .order_by(RoutingDecision.id.desc())
        .limit(1)
    )
    incidents = await session.scalars(
        select(Incident)
        .options(selectinload(Incident.links))
        .join(IncidentLink, IncidentLink.incident_id == Incident.id)
        .where(IncidentLink.ticket_id == ticket.id, IncidentLink.active)
    )
    return TicketRouting(
        classification=ClassificationOut.model_validate(classification) if classification else None,
        routing=RoutingOut.model_validate(decision) if decision else None,
        incidents=[await incident_out(session, i) for i in incidents.unique()],
    )
