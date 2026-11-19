from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.reference import Customer, SlaTerm
from app.models.tickets import SlaTracking, Ticket
from app.schemas.common import Page
from app.schemas.tickets import CustomerDetail, CustomerOut, SlaTermOut

router = APIRouter(prefix="/customers", tags=["customers"])
Reader = Annotated[Principal, Depends(require(Permission.CUSTOMERS_READ))]

_stats = (
    select(
        Ticket.customer_id,
        func.count(Ticket.id).label("tickets"),
        func.sum(case((SlaTracking.resolution_breached.is_(True), 1), else_=0)).label("breaches"),
        func.coalesce(func.sum(SlaTracking.credit_usd), 0).label("credits"),
    )
    .outerjoin(SlaTracking, SlaTracking.ticket_id == Ticket.id)
    .group_by(Ticket.customer_id)
    .subquery("customer_stats")
)


def _out(customer: Customer, tickets: int | None, breaches: int | None, credits: Decimal | None) -> CustomerOut:
    out = CustomerOut.model_validate(customer)
    out.ticket_count, out.sla_breaches, out.credits_usd = tickets or 0, breaches or 0, credits or Decimal("0")
    return out


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    session: SessionDep,
    principal: Reader,
    tier: Literal["Enterprise", "Business", "Standard"] | None = None,
    region: Literal["IN", "UAE"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[CustomerOut]:
    query = (
        select(Customer, _stats.c.tickets, _stats.c.breaches, _stats.c.credits)
        .outerjoin(_stats, _stats.c.customer_id == Customer.customer_id)
        .where(region_filter(principal, Customer.region))
    )
    if tier:
        query = query.where(Customer.tier == tier)
    if region:
        query = query.where(Customer.region == region)
    if q:
        query = query.where(Customer.name.ilike(f"%{q}%") | Customer.customer_id.ilike(f"%{q}%"))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.execute(query.order_by(Customer.customer_id).offset((page - 1) * page_size).limit(page_size))
    return Page[CustomerOut](items=[_out(*r) for r in rows.all()], total=total, page=page, page_size=page_size)


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer(customer_id: str, session: SessionDep, principal: Reader) -> CustomerDetail:
    row = (
        await session.execute(
            select(Customer, _stats.c.tickets, _stats.c.breaches, _stats.c.credits)
            .outerjoin(_stats, _stats.c.customer_id == Customer.customer_id)
            .where(Customer.customer_id == customer_id, region_filter(principal, Customer.region))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    terms = await session.scalars(select(SlaTerm).where(SlaTerm.tier == row[0].tier).order_by(SlaTerm.priority))
    return CustomerDetail(**_out(*row).model_dump(), sla_terms=[SlaTermOut.model_validate(t) for t in terms])
