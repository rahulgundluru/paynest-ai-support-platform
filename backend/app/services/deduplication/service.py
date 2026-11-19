"""Persists duplicate/incident detection. Idempotent: automatic groupings are rebuilt on each run;
any incident a person has edited (link/unlink) is left untouched and its tickets are excluded."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.processing import Incident, IncidentLink
from app.models.tickets import Ticket
from app.services import audit
from app.services.deduplication.detector import (
    RULESET_VERSION,
    DedupeConfig,
    TicketView,
    find_incidents,
    find_resubmissions,
)
from app.services.normalization.rules import CATEGORY_QUEUE

INCIDENT_QUEUE = "Incident-Response"


async def run_detection(
    session: AsyncSession, config: DedupeConfig = DedupeConfig(), actor: uuid.UUID | None = None
) -> dict[str, Any]:
    incidents = list(await session.scalars(select(Incident).options(selectinload(Incident.links))))
    manual = [i for i in incidents if any(link.linked_by is not None for link in i.links)]
    protected = {str(link.ticket_id) for i in manual for link in i.links}
    automatic_ids = [i.id for i in incidents if i not in manual]
    if automatic_ids:
        await session.execute(delete(Incident).where(Incident.id.in_(automatic_ids)))

    tickets = list(await session.scalars(select(Ticket)))
    by_id = {str(t.id): t for t in tickets}
    views = [
        TicketView(
            id=str(t.id),
            external_id=t.external_id,
            customer_id=t.customer_id,
            channel=t.channel,
            created_at=t.created_at,
            subject=t.subject_redacted,
            body=t.body_redacted,
            category=t.customer_category,
        )
        for t in tickets
        if str(t.id) not in protected
    ]

    stats: Counter[str] = Counter()
    resubmits = find_resubmissions(views, config)
    chains: dict[str, Incident] = {}
    for link in resubmits:
        parent, child = by_id[link.parent_id], by_id[link.ticket_id]
        incident = chains.get(link.parent_id)
        if incident is None:
            incident = Incident(
                kind="resubmission",
                customer_id=parent.customer_id,
                region=parent.region,
                master_ticket_id=parent.id,
                owner_queue=parent.final_queue or parent.first_queue,
                category=parent.customer_category,
                rule_id=link.rule_id,
                rule_version=RULESET_VERSION,
                first_ticket_at=parent.created_at,
                declared_at=child.created_at,
                links=[
                    IncidentLink(
                        ticket_id=parent.id,
                        role="master",
                        rule_id=link.rule_id,
                        reason="Original ticket",
                        confidence=1.0,
                    )
                ],
            )
            chains[link.parent_id] = incident
            session.add(incident)
        incident.links.append(
            IncidentLink(
                ticket_id=child.id,
                role="resubmit",
                rule_id=link.rule_id,
                reason=link.reason,
                confidence=link.confidence,
            )
        )
        stats["resubmission_links"] += 1
    stats["resubmission_cases"] = len(chains)

    linked = {link.ticket_id for link in resubmits}
    for candidate in find_incidents(views, exclude=linked, config=config):
        first = by_id[candidate.ticket_ids[0]]
        session.add(
            Incident(
                kind="incident",
                customer_id=candidate.customer_id,
                region=first.region,
                master_ticket_id=first.id,
                owner_queue=INCIDENT_QUEUE,
                category=candidate.category,
                rule_id=candidate.rule_id,
                rule_version=RULESET_VERSION,
                first_ticket_at=candidate.first_at,
                declared_at=candidate.declared_at,
                links=[
                    IncidentLink(
                        ticket_id=by_id[tid].id,
                        role="master" if i == 0 else "member",
                        rule_id=candidate.rule_id,
                        reason=(
                            f"{len(candidate.ticket_ids)} '{candidate.category}' tickets from one customer, "
                            f"each within {config.incident_gap.total_seconds() / 3600:.0f} h of the previous"
                        ),
                        confidence=0.8,
                    )
                    for i, tid in enumerate(candidate.ticket_ids)
                ],
            )
        )
        stats["incidents"] += 1
        stats["incident_tickets"] += len(candidate.ticket_ids)
    stats["manual_incidents_preserved"] = len(manual)
    await audit.record(session, "dedupe.detected", actor_user_id=actor, details=dict(stats))
    await session.commit()
    return dict(stats)


def queue_for_category(category: str | None) -> str | None:
    return CATEGORY_QUEUE.get(category) if category else None
