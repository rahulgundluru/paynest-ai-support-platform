from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.approvals import Approval, LearnedMemory
from app.models.tickets import PiiDetection, PiiVaultEntry, Ticket
from app.schemas.approvals import (
    ApprovalDetail,
    ApprovalEventOut,
    ApprovalSummary,
    DecisionRequest,
    DraftRequest,
    MemoryOut,
    RevealRequest,
    RevealResponse,
)
from app.schemas.common import Page
from app.services import audit
from app.services.approvals.service import WorkflowError, decide, edit_draft
from app.services.pii import vault

router = APIRouter(tags=["approvals"])
Reader = Annotated[Principal, Depends(require(Permission.APPROVALS_READ))]
Editor = Annotated[Principal, Depends(require(Permission.APPROVALS_EDIT))]
Decider = Annotated[Principal, Depends(require(Permission.APPROVALS_DECIDE))]
SECOND_PERSON_RULES = {"R6", "R7"}  # pay/billing P1 and statutory answers: author != approver


def _summary(a: Approval, ticket: Ticket | None) -> ApprovalSummary:
    out = ApprovalSummary.model_validate(a)
    out.ticket_external_id = ticket.external_id if ticket else None
    out.summary = str(a.evidence.get("summary", ""))
    out.sla_breached = (a.evidence.get("sla") or {}).get("resolution_breached")
    out.validation_passed = a.validation.get("passed") if a.validation else None
    return out


def _detail(a: Approval, ticket: Ticket | None) -> ApprovalDetail:
    return ApprovalDetail(
        **_summary(a, ticket).model_dump(),
        evidence=a.evidence,
        draft_text=a.draft_text,
        validation=a.validation,
        events=[ApprovalEventOut.model_validate(e) for e in a.events],
        requires_second_person=a.rule_id in SECOND_PERSON_RULES,
    )


@router.get("/approvals", response_model=Page[ApprovalSummary])
async def list_approvals(
    session: SessionDep,
    principal: Reader,
    status: Literal["pending", "approved", "rejected", "escalated", "resolved", "all"] = "pending",
    queue: str | None = None,
    lane: str | None = None,
    rule_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[ApprovalSummary]:
    query = (
        select(Approval, Ticket)
        .join(Ticket, Ticket.id == Approval.ticket_id)
        .where(region_filter(principal, Approval.region))
    )
    filters = (
        (Approval.status, None if status == "all" else status),
        (Approval.queue, queue),
        (Approval.lane, lane),
        (Approval.rule_id, rule_id),
    )
    for column, value in filters:
        if value:
            query = query.where(column == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Most urgent first: blocked/security items, then by ticket age.
    rows = await session.execute(
        query.order_by((Approval.lane == "block").desc(), Ticket.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page[ApprovalSummary](
        items=[_summary(a, t) for a, t in rows.all()], total=total, page=page, page_size=page_size
    )


async def _load(session: SessionDep, principal: Principal, approval_id: uuid.UUID) -> tuple[Approval, Ticket]:
    row = (
        await session.execute(
            select(Approval, Ticket)
            .options(selectinload(Approval.events))
            .join(Ticket, Ticket.id == Approval.ticket_id)
            .where(Approval.id == approval_id, region_filter(principal, Approval.region))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return row[0], row[1]


@router.get("/approvals/{approval_id}", response_model=ApprovalDetail)
async def get_approval(approval_id: uuid.UUID, session: SessionDep, principal: Reader) -> ApprovalDetail:
    approval, ticket = await _load(session, principal, approval_id)
    return _detail(approval, ticket)


@router.put("/approvals/{approval_id}/draft", response_model=ApprovalDetail)
async def put_draft(
    approval_id: uuid.UUID, body: DraftRequest, session: SessionDep, principal: Editor
) -> ApprovalDetail:
    """Save the reply draft (redacted text with tokens). It is validated immediately; results are returned."""
    approval, ticket = await _load(session, principal, approval_id)
    try:
        await edit_draft(session, approval, ticket, body.text, principal.user.id)
    except WorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    await session.commit()
    await session.refresh(approval, attribute_names=["events"])
    return _detail(approval, ticket)


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalDetail)
async def decision(
    approval_id: uuid.UUID, body: DecisionRequest, session: SessionDep, principal: Decider
) -> ApprovalDetail:
    approval, ticket = await _load(session, principal, approval_id)
    if body.action == "approve" and approval.rule_id in SECOND_PERSON_RULES:
        last_editor = next((e.actor_user_id for e in reversed(approval.events) if e.action == "edited"), None)
        if last_editor == principal.user.id:
            raise HTTPException(status_code=403, detail="A second person must approve this draft (two-person rule)")
    try:
        await decide(session, approval, ticket, body.action, principal.user.id, body.note, body.target)
    except WorkflowError as exc:
        await session.commit()  # keep the refreshed validation result even when approval is refused
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    await session.commit()
    await session.refresh(approval, attribute_names=["events"])
    return _detail(approval, ticket)


# Spec-compatible shortcuts
@router.post("/approvals/{approval_id}/approve", response_model=ApprovalDetail)
async def approve(approval_id: uuid.UUID, session: SessionDep, principal: Decider) -> ApprovalDetail:
    return await decision(approval_id, DecisionRequest(action="approve"), session, principal)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalDetail)
async def reject(
    approval_id: uuid.UUID, session: SessionDep, principal: Decider, note: str | None = None
) -> ApprovalDetail:
    return await decision(approval_id, DecisionRequest(action="reject", note=note), session, principal)


@router.post("/approvals/{approval_id}/escalate", response_model=ApprovalDetail)
async def escalate(
    approval_id: uuid.UUID, session: SessionDep, principal: Decider, target: str = "L2", note: str | None = None
) -> ApprovalDetail:
    return await decision(approval_id, DecisionRequest(action="escalate", target=target, note=note), session, principal)


@router.get("/memory", response_model=Page[MemoryOut])
async def list_memory(
    session: SessionDep,
    principal: Reader,
    customer_id: str | None = None,
    include_expired: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[MemoryOut]:
    """Human-approved resolutions. Filtered to the caller's regions; expired entries hidden by default."""
    query = select(LearnedMemory).where(region_filter(principal, LearnedMemory.region))
    if customer_id:
        query = query.where(LearnedMemory.customer_id == customer_id)
    if not include_expired:
        query = query.where(or_(LearnedMemory.valid_until.is_(None), LearnedMemory.valid_until >= date.today()))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(LearnedMemory.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[MemoryOut](
        items=[MemoryOut.model_validate(m) for m in rows], total=total, page=page, page_size=page_size
    )


@router.post("/tickets/{ref}/pii/{token}/reveal", response_model=RevealResponse)
async def reveal_pii(
    ref: str,
    token: str,
    body: RevealRequest,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require(Permission.PII_REVEAL))],
) -> RevealResponse:
    """DPO-only access to one original value, with a stated reason. Audited without the value itself."""
    condition = Ticket.external_id == ref
    try:
        condition = or_(condition, Ticket.id == uuid.UUID(ref))
    except ValueError:
        pass
    ticket = await session.scalar(select(Ticket).where(condition, region_filter(principal, Ticket.region)))
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    wanted = token if token.startswith("<") else f"<{token}>"
    entry = await session.scalar(
        select(PiiVaultEntry).where(
            PiiVaultEntry.source_record_id == ticket.source_record_id, PiiVaultEntry.token == wanted
        )
    )
    if entry is None or not await session.scalar(
        select(func.count()).where(PiiDetection.ticket_id == ticket.id, PiiDetection.token == wanted)
    ):
        raise HTTPException(status_code=404, detail="Token not found for this ticket")
    now = datetime.now(tz=UTC)
    if entry.retention_until < now:
        raise HTTPException(status_code=410, detail="Retention period has ended for this value")
    await audit.record(
        session, "pii.revealed", actor_user_id=principal.user.id, entity_type="ticket",
        entity_id=ticket.external_id or str(ticket.id), region=ticket.region,
        details={"token": wanted, "entity_type": entry.entity_type, "reason": body.reason},
    )  # fmt: skip
    await session.commit()
    return RevealResponse(
        token=wanted,
        entity_type=entry.entity_type,
        value=vault.decrypt(entry.value_encrypted),
        revealed_at=now,
        retention_until=entry.retention_until,
    )
