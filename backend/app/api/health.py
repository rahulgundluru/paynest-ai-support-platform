"""Liveness and readiness probes (used by Docker, ECS and the ALB)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionDep

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    """Process is up. Does not touch dependencies."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def ready(session: SessionDep, response: Response) -> dict[str, Any]:
    """Database reachable, migrations applied, pgvector installed."""
    checks: dict[str, Any] = {"database": "unavailable", "migration": None, "pgvector": "unknown"}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
        has_vector = await session.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"))
        checks["pgvector"] = "ok" if has_vector else "missing"
        checks["migration"] = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception as exc:  # readiness must report, not crash
        log.warning("readiness check failed", extra={"error_type": type(exc).__name__})
    healthy = checks["database"] == "ok" and checks["pgvector"] == "ok" and bool(checks["migration"])
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "unavailable", "checks": checks}
