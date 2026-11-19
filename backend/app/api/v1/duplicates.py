from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.processing import Incident, IncidentLink
from app.models.reference import Customer
from app.models.tickets import Ticket
from app.schemas.common import Page
from app.schemas.processing import IncidentDetail, IncidentLinkOut, IncidentOut, LinkRequest
from app.services import audit
from app.services.deduplication.service import run_detection

router = APIRouter(prefix="/duplicates", tags=["duplicates"])
Reader = Annotated[Principal, Depends(require(Permission.TICKETS_READ))]
Manager = Annotated[Principal, Depends(require(Permission.INCIDENTS_MANAGE))]


async def incident_out(session: SessionDep, incident: Incident) -> IncidentOut:
    master = await session.get(Ticket, incident.master_ticket_id)
    customer = await session.get(Customer, incident.customer_id) if incident.customer_id else None
    return IncidentOut(
        id=incident.id,
        kind=incident.kind,
        customer_id=incident.customer_id,
        customer_name=customer.name if customer else None,
        region=incident.region,
        master_external_id=master.external_id if master else None,
        owner_queue=incident.owner_queue,
        category=incident.category,
        rule_id=incident.rule_id,
        first_ticket_at=incident.first_ticket_at,
        declared_at=incident.declared_at,
        status=incident.status,
        ticket_count=sum(1 for link in incident.links if link.active),
    )


@router.get("", response_model=Page[IncidentOut])
async def list_incidents(
    session: SessionDep,
    principal: Reader,
    kind: Literal["resubmission", "incident"] | None = None,
    customer_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[IncidentOut]:
    query = select(Incident).options(selectinload(Incident.links)).where(region_filter(principal, Incident.region))
    if kind:
        query = query.where(Incident.kind == kind)
    if customer_id:
        query = query.where(Incident.customer_id == customer_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(Incident.declared_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[IncidentOut](
        items=[await incident_out(session, i) for i in rows], total=total, page=page, page_size=page_size
    )


async def _load(session: SessionDep, principal: Principal, incident_id: uuid.UUID) -> Incident:
    incident = await session.scalar(
        select(Incident)
        .options(selectinload(Incident.links))
        .where(Incident.id == incident_id, region_filter(principal, Incident.region))
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


async def _detail(session: SessionDep, incident: Incident) -> IncidentDetail:
    links: list[IncidentLinkOut] = []
    for link in incident.links:
        t = await session.get(Ticket, link.ticket_id)
        if t is None:
            continue
        links.append(
            IncidentLinkOut(
                ticket_id=t.id,
                external_id=t.external_id,
                channel=t.channel,
                created_at=t.created_at,
                subject_redacted=t.subject_redacted,
                role=link.role,
                rule_id=link.rule_id,
                reason=link.reason,
                confidence=link.confidence,
                active=link.active,
                manual=link.linked_by is not None,
            )
        )
    links.sort(key=lambda x: x.created_at)
    return IncidentDetail(**(await incident_out(session, incident)).model_dump(), links=links)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: uuid.UUID, session: SessionDep, principal: Reader) -> IncidentDetail:
    return await _detail(session, await _load(session, principal, incident_id))


@router.post("/detect")
async def detect(session: SessionDep, principal: Manager) -> dict[str, int]:
    return await run_detection(session, actor=principal.user.id)


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


@router.post("/{incident_id}/unlink", response_model=IncidentDetail)
async def unlink(incident_id: uuid.UUID, body: LinkRequest, session: SessionDep, principal: Manager) -> IncidentDetail:
    """A person separates a ticket from the case. Recorded as a manual decision that re-detection respects."""
    incident = await _load(session, principal, incident_id)
    ticket = await _ticket(session, principal, body.ticket_ref)
    link = next((lk for lk in incident.links if lk.ticket_id == ticket.id), None)
    if link is None:
        raise HTTPException(status_code=404, detail="Ticket is not linked to this incident")
    if link.role == "master":
        raise HTTPException(
            status_code=409, detail="The master ticket cannot be unlinked; dissolve the incident instead"
        )
    link.active, link.linked_by = False, principal.user.id
    await audit.record(
        session, "incident.unlinked", actor_user_id=principal.user.id, entity_type="incident",
        entity_id=str(incident.id), region=incident.region, details={"ticket": ticket.external_id},
    )  # fmt: skip
    await session.commit()
    return await _detail(session, incident)


@router.post("/{incident_id}/link", response_model=IncidentDetail)
async def link(incident_id: uuid.UUID, body: LinkRequest, session: SessionDep, principal: Manager) -> IncidentDetail:
    """A person adds a ticket to the case. Only tickets of the same customer can be grouped."""
    incident = await _load(session, principal, incident_id)
    ticket = await _ticket(session, principal, body.ticket_ref)
    if ticket.customer_id is None or ticket.customer_id != incident.customer_id:
        raise HTTPException(status_code=422, detail="Only tickets of the same verified customer can be linked")
    existing = next((lk for lk in incident.links if lk.ticket_id == ticket.id), None)
    if existing:
        existing.active, existing.linked_by = True, principal.user.id
    else:
        incident.links.append(
            IncidentLink(
                ticket_id=ticket.id,
                role="resubmit" if incident.kind == "resubmission" else "member",
                rule_id="MANUAL",
                reason="Linked by a support lead",
                confidence=1.0,
                linked_by=principal.user.id,
            )
        )
    await audit.record(
        session, "incident.linked", actor_user_id=principal.user.id, entity_type="incident",
        entity_id=str(incident.id), region=incident.region, details={"ticket": ticket.external_id},
    )  # fmt: skip
    await session.commit()
    await session.refresh(incident, attribute_names=["links"])
    return await _detail(session, incident)
