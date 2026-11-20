"""Ticket creation and the per-ticket pipeline (run, re-run, live progress)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.api.scoping import region_filter
from app.api.v1.processing_ai import _ticket
from app.core.rbac import Permission
from app.db.session import get_sessionmaker
from app.models.identity import Region
from app.models.processing import PipelineRun
from app.models.reference import Customer
from app.models.tickets import Ticket
from app.schemas.pipeline import CreatedTicket, NewTicketRequest, PipelineRunOut
from app.services import audit
from app.services.intake.service import NewTicket, create_ticket
from app.services.pipeline import runner

router = APIRouter(tags=["tickets"])
Creator = Annotated[Principal, Depends(require(Permission.TICKETS_CREATE))]
Processor = Annotated[Principal, Depends(require(Permission.TICKETS_PROCESS))]
Reader = Annotated[Principal, Depends(require(Permission.TICKETS_READ))]


def run_out(run: PipelineRun, ticket_ref: str | None) -> PipelineRunOut:
    out = PipelineRunOut.model_validate(run)
    out.ticket_ref = ticket_ref
    return out


def _schedule(background: BackgroundTasks, run_id: uuid.UUID, settings: SettingsDep) -> None:
    background.add_task(runner.execute_run, get_sessionmaker(), run_id, settings)


@router.post("/tickets", response_model=CreatedTicket, status_code=status.HTTP_201_CREATED)
async def create(
    body: NewTicketRequest, background: BackgroundTasks, session: SessionDep, settings: SettingsDep,
    principal: Creator,
) -> CreatedTicket:  # fmt: skip
    """Log a ticket and run it through the full pipeline. Returns at once; the AI steps continue in the
    background and the run can be followed at `GET /pipeline-runs/{id}`."""
    regions = {r.value for r in principal.user.regions}
    if body.customer_id:
        customer = await session.get(Customer, body.customer_id)
        if customer is None:
            raise HTTPException(status_code=422, detail=f"Customer {body.customer_id} is not in the customer master")
        if customer.region not in regions:
            raise HTTPException(status_code=403, detail="That customer is outside your region scope")
    elif regions != {r.value for r in Region}:
        raise HTTPException(
            status_code=403, detail="Only users scoped to all regions can log a ticket for an unverified customer"
        )
    result = await create_ticket(
        session,
        NewTicket(
            channel=body.channel, customer_id=body.customer_id, subject=body.subject, body=body.body,
            priority=body.priority, customer_category=body.customer_category, received_at=body.received_at,
        ),
        actor=principal.user.id,
        retention_days=settings.pii_retention_days,
    )  # fmt: skip
    run = await runner.start_run(
        session, result.ticket, trigger="create", actor=principal.user.id, settings=settings,
        intake_steps=result.steps,
    )  # fmt: skip
    await session.commit()
    _schedule(background, run.id, settings)
    ref = result.ticket.external_id or str(result.ticket.id)
    return CreatedTicket(ticket_ref=ref, run=run_out(run, ref))


@router.post("/tickets/{ref}/pipeline", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def rerun(
    ref: str, background: BackgroundTasks, session: SessionDep, settings: SettingsDep, principal: Processor
) -> PipelineRunOut:
    """Run the post-intake pipeline again for any ticket (imported or app-entered), e.g. after enabling AI."""
    ticket = await _ticket(session, principal, ref)
    if await runner.has_active_run(session, ticket.id):
        raise HTTPException(status_code=409, detail="A pipeline run for this ticket is already in progress")
    run = await runner.start_run(session, ticket, trigger="rerun", actor=principal.user.id, settings=settings)
    await audit.record(
        session, "pipeline.started", actor_user_id=principal.user.id, entity_type="ticket",
        entity_id=ticket.external_id or str(ticket.id), region=ticket.region, details={"run": str(run.id)},
    )  # fmt: skip
    await session.commit()
    _schedule(background, run.id, settings)
    return run_out(run, ticket.external_id)


@router.get("/tickets/{ref}/pipeline", response_model=list[PipelineRunOut])
async def ticket_runs(ref: str, session: SessionDep, principal: Reader) -> list[PipelineRunOut]:
    """The ticket's latest pipeline runs, newest first."""
    ticket = await _ticket(session, principal, ref)
    return [run_out(r, ticket.external_id) for r in await runner.latest_runs(session, ticket.id)]


@router.get("/pipeline-runs/{run_id}", response_model=PipelineRunOut)
async def get_run(run_id: uuid.UUID, session: SessionDep, principal: Reader) -> PipelineRunOut:
    row = (
        await session.execute(
            select(PipelineRun, Ticket.external_id)
            .join(Ticket, Ticket.id == PipelineRun.ticket_id)
            .where(PipelineRun.id == run_id, region_filter(principal, Ticket.region))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run_out(row[0], row[1])
