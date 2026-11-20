"""Audit trail writer. Callers pass identifiers and outcomes only, never ticket text or PII."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.models.audit import AuditLog


async def record(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    region: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            region=region,
            request_id=request_id_var.get(),
            details=details or {},
        )
    )
