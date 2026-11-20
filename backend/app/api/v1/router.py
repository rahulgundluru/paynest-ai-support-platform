from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    approvals,
    audit_logs,
    auth,
    customers,
    dashboard,
    duplicates,
    evaluations,
    knowledge,
    monitor,
    processing,
    processing_ai,
    settings,
    sla,
    tickets,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(audit_logs.router)
api_router.include_router(monitor.router)
api_router.include_router(processing.router)
api_router.include_router(tickets.router)
api_router.include_router(customers.router)
api_router.include_router(sla.router)
api_router.include_router(knowledge.router)
api_router.include_router(duplicates.router)
api_router.include_router(processing_ai.router)
api_router.include_router(approvals.router)
api_router.include_router(dashboard.router)
api_router.include_router(settings.router)
api_router.include_router(evaluations.router)
api_router.include_router(analytics.router)
