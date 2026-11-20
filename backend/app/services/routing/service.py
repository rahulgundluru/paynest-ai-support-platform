"""Builds routing inputs from stored ticket state and records every decision with its rule and inputs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processing import Classification, Incident, IncidentLink, RoutingDecision
from app.models.reference import Customer
from app.models.tickets import Ticket
from app.services.classification.service import injection_signals
from app.services.routing.engine import RoutingConfig, RoutingInput, inputs_hash, route


async def build_input(session: AsyncSession, ticket: Ticket) -> RoutingInput:
    customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
    classification = await session.scalar(
        select(Classification)
        .where(Classification.ticket_id == ticket.id, Classification.status == "ok")
        .order_by(Classification.created_at.desc())
        .limit(1)
    )
    membership = (
        await session.execute(
            select(Incident.kind, Incident.owner_queue, IncidentLink.role)
            .join(IncidentLink, IncidentLink.incident_id == Incident.id)
            .where(IncidentLink.ticket_id == ticket.id, IncidentLink.active, Incident.status == "open")
        )
    ).first()
    resubmission_queue = membership.owner_queue if membership and membership.role == "resubmit" else None
    incident_queue = membership.owner_queue if membership and membership.kind == "incident" else None
    if classification:
        category, source = classification.category, "classifier"
        priority = classification.priority or ticket.priority
    else:
        category, source, priority = (
            ticket.customer_category,
            "customer_pick" if ticket.customer_category else "none",
            ticket.priority,
        )
    return RoutingInput(
        category=category,
        category_source=source,
        priority=priority,
        tier=customer.tier if customer else None,
        region=ticket.region,
        customer_resolved=customer is not None,
        is_injection=bool(classification and classification.is_injection)
        or bool(injection_signals(ticket.subject_redacted, ticket.body_redacted)),
        classifier_confidence=classification.confidence if classification else None,
        requires_human=bool(classification and classification.requires_human),
        incident_queue=incident_queue,
        resubmission_of_queue=resubmission_queue,
        in_payroll_window=ticket.in_payroll_window,
    )


async def route_ticket(
    session: AsyncSession, ticket: Ticket, config: RoutingConfig = RoutingConfig()
) -> RoutingDecision:
    inp = await build_input(session, ticket)
    decision = route(inp, config)
    record = RoutingDecision(
        ticket_id=ticket.id,
        lane=decision.lane,
        queue=decision.queue,
        support_level=decision.support_level,
        rule_id=decision.rule_id,
        rule_version=decision.rule_version,
        reason=decision.reason,
        requires_approval=decision.requires_approval,
        inputs={k: v for k, v in inp.__dict__.items()},
        inputs_sha256=inputs_hash(inp, config),
    )
    session.add(record)
    return record


async def route_all(session: AsyncSession, config: RoutingConfig = RoutingConfig()) -> dict[str, Any]:
    lanes: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    for ticket in await session.scalars(select(Ticket).order_by(Ticket.created_at)):
        decision = await route_ticket(session, ticket, config)
        lanes[decision.lane] += 1
        rules[decision.rule_id] += 1
    await session.commit()
    return {"lanes": dict(lanes), "rules": dict(rules)}
