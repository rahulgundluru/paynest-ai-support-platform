from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import Principal, SessionDep, require
from app.core.rbac import Permission
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditLogOut])
async def list_audit_logs(
    session: SessionDep,
    _: Annotated[Principal, Depends(require(Permission.AUDIT_READ))],
    action: Annotated[str | None, Query(max_length=100)] = None,
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AuditLogOut]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size
    )
