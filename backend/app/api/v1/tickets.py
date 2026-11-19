from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.reference import Customer
from app.models.tickets import NormalizationLog, PiiDetection, SlaTracking, SourceRecord, Ticket
from app.schemas.common import Page
from app.schemas.tickets import (
    EventOut,
    MessageOut,
    NormalizationOut,
    PiiDetectionOut,
    SlaOut,
    TicketDetail,
    TicketSummary,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])
Reader = Annotated[Principal, Depends(require(Permission.TICKETS_READ))]

_pii_count = (
    select(PiiDetection.ticket_id, func.count().label("n")).group_by(PiiDetection.ticket_id).subquery("pii_counts")
)
SORTS: dict[str, Any] = {
    "created_at": Ticket.created_at,
    "external_id": Ticket.external_id,
    "priority": Ticket.priority,
    "reassignment_count": Ticket.reassignment_count,
}


def _summary(ticket: Ticket, customer: Customer | None, pii: int | None, breached: bool | None) -> TicketSummary:
    out = TicketSummary.model_validate(ticket)
    out.customer_name = customer.name if customer else None
    out.customer_tier = customer.tier if customer else None
    out.pii_entity_count = pii or 0
    out.sla_resolution_breached = breached
    return out


@router.get("", response_model=Page[TicketSummary])
async def list_tickets(
    session: SessionDep,
    principal: Reader,
    q: Annotated[str | None, Query(max_length=100, description="Ticket id or text in the redacted subject")] = None,
    channel: str | None = None,
    priority: Literal["P1", "P2", "P3"] | None = None,
    category: str | None = None,
    region: Literal["IN", "UAE"] | None = None,
    customer_id: str | None = None,
    status: str | None = None,
    queue: str | None = None,
    ingestion_status: str | None = None,
    sla_breached: bool | None = None,
    payroll_window: bool | None = None,
    reassigned: bool | None = None,
    sort: Literal["created_at", "external_id", "priority", "reassignment_count"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
) -> Page[TicketSummary]:
    query = (
        select(Ticket, Customer, _pii_count.c.n, SlaTracking.resolution_breached)
        .outerjoin(Customer, Customer.customer_id == Ticket.customer_id)
        .outerjoin(_pii_count, _pii_count.c.ticket_id == Ticket.id)
        .outerjoin(SlaTracking, SlaTracking.ticket_id == Ticket.id)
        .where(region_filter(principal, Ticket.region))
    )
    filters: list[Any] = []
    if q:
        term = f"%{q.strip()}%"
        filters.append(or_(Ticket.external_id.ilike(term), Ticket.subject_redacted.ilike(term)))
    for column, value in (
        (Ticket.channel, channel),
        (Ticket.priority, priority),
        (Ticket.customer_category, category),
        (Ticket.region, region),
        (Ticket.customer_id, customer_id),
        (Ticket.status, status),
        (Ticket.final_queue, queue),
        (Ticket.ingestion_status, ingestion_status),
    ):
        if value is not None:
            filters.append(column == value)
    if sla_breached is not None:
        filters.append(SlaTracking.resolution_breached.is_(sla_breached))
    if payroll_window is not None:
        filters.append(Ticket.in_payroll_window.is_(payroll_window))
    if reassigned is not None:
        filters.append(Ticket.reassignment_count > 0 if reassigned else Ticket.reassignment_count == 0)
    query = query.where(*filters)

    total = await session.scalar(select(func.count()).select_from(query.with_only_columns(Ticket.id).subquery())) or 0
    column = SORTS[sort]
    ordering = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    rows = await session.execute(query.order_by(ordering, Ticket.id).offset((page - 1) * page_size).limit(page_size))
    return Page[TicketSummary](
        items=[_summary(t, c, n, b) for t, c, n, b in rows.all()], total=total, page=page, page_size=page_size
    )


async def _load(session: SessionDep, principal: Principal, ref: str) -> Ticket:
    condition = Ticket.external_id == ref
    try:
        condition = or_(condition, Ticket.id == uuid.UUID(ref))
    except ValueError:
        pass
    ticket = await session.scalar(
        select(Ticket)
        .options(selectinload(Ticket.messages), selectinload(Ticket.events))
        .where(condition, region_filter(principal, Ticket.region))
    )
    if ticket is None:  # also returned for out-of-region tickets: existence is not disclosed
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.get("/{ref}", response_model=TicketDetail)
async def get_ticket(ref: str, session: SessionDep, principal: Reader) -> TicketDetail:
    ticket = await _load(session, principal, ref)
    customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
    record = await session.get(SourceRecord, ticket.source_record_id)
    sla = await session.get(SlaTracking, ticket.id)
    detections = list(
        await session.scalars(select(PiiDetection).where(PiiDetection.ticket_id == ticket.id).order_by(PiiDetection.id))
    )
    norm = list(
        await session.scalars(
            select(NormalizationLog).where(NormalizationLog.ticket_id == ticket.id).order_by(NormalizationLog.id)
        )
    )
    summary = _summary(ticket, customer, len(detections), sla.resolution_breached if sla else None)
    attributes = {k: v for k, v in ticket.attributes.items() if k != "fingerprint"}
    return TicketDetail(
        **summary.model_dump(),
        customer_resolution=ticket.customer_resolution,
        region_source=ticket.region_source,
        partner_id=ticket.partner_id,
        body_redacted=ticket.body_redacted,
        language_hint=ticket.language_hint,
        final_category_label=ticket.final_category_label,
        first_response_at=ticket.first_response_at,
        resolved_at=ticket.resolved_at,
        review_reasons=ticket.review_reasons,
        attributes=attributes,
        source_file=record.source_file if record else "",
        source_record_index=record.record_index if record else -1,
        messages=[MessageOut.model_validate(m) for m in ticket.messages],
        events=[EventOut.model_validate(e) for e in ticket.events],
        pii_detections=[PiiDetectionOut.model_validate(d) for d in detections],
        normalization=[NormalizationOut.model_validate(n) for n in norm],
        sla=SlaOut.model_validate(sla) if sla else None,
    )


@router.get("/{ref}/timeline", response_model=list[dict[str, Any]])
async def ticket_timeline(ref: str, session: SessionDep, principal: Reader) -> list[dict[str, Any]]:
    ticket = await _load(session, principal, ref)
    items: list[dict[str, Any]] = [
        {"kind": "event", "at": e.occurred_at, "type": e.event_type, "actor": e.actor, "data": e.data}
        for e in ticket.events
    ]
    items += [
        {"kind": "message", "at": m.sent_at, "type": m.author_type, "actor": None, "data": {"text": m.body_redacted}}
        for m in ticket.messages
        if m.sent_at is not None
    ]
    return sorted(items, key=lambda i: i["at"])
