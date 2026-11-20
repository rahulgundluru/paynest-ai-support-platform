from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.reference import Customer, FinanceSlaBreach
from app.models.tickets import SlaTracking, Ticket
from app.schemas.tickets import Reconciliation, ReconciliationRow

router = APIRouter(prefix="/sla", tags=["sla"])


@router.get("/reconciliation", response_model=Reconciliation)
async def reconciliation(
    session: SessionDep, principal: Annotated[Principal, Depends(require(Permission.SLA_READ))]
) -> Reconciliation:
    """Finance's breach/credit list vs the SLA engine's independent calculation, ticket by ticket."""
    rows = (
        await session.execute(
            select(FinanceSlaBreach, SlaTracking)
            .join(Customer, Customer.customer_id == FinanceSlaBreach.customer_id)
            .outerjoin(Ticket, Ticket.external_id == FinanceSlaBreach.ticket_external_id)
            .outerjoin(SlaTracking, SlaTracking.ticket_id == Ticket.id)
            .where(region_filter(principal, Customer.region))
            .order_by(FinanceSlaBreach.breach_id)
        )
    ).all()
    out: list[ReconciliationRow] = []
    for finance, sla in rows:
        engine_credit = sla.credit_usd if sla else None
        out.append(
            ReconciliationRow(
                breach_id=finance.breach_id,
                ticket_external_id=finance.ticket_external_id,
                finance_credit_usd=finance.credit_usd,
                engine_credit_usd=engine_credit,
                finance_actual_h=finance.actual_resolution_h,
                engine_resolution_h=sla.resolution_hours if sla else None,
                matches=engine_credit is not None and engine_credit == finance.credit_usd,
            )
        )
    finance_ids = {r.ticket_external_id for r in out}
    engine_only = await session.scalars(
        select(Ticket.external_id)
        .join(SlaTracking, SlaTracking.ticket_id == Ticket.id)
        .where(
            SlaTracking.credit_usd.is_not(None),
            Ticket.external_id.is_not(None),
            region_filter(principal, Ticket.region),
        )
    )
    matched = sum(1 for r in out if r.matches)
    return Reconciliation(
        finance_rows=len(out),
        matched=matched,
        mismatched=len(out) - matched,
        finance_total_usd=sum((r.finance_credit_usd for r in out), Decimal("0")),
        engine_total_for_finance_rows_usd=sum((r.engine_credit_usd or Decimal("0") for r in out), Decimal("0")),
        engine_breaches_not_in_finance_list=sorted(e for e in engine_only if e and e not in finance_ids),
        rows=out,
    )
