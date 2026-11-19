from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import audit_logs, auth, customers, processing, sla, tickets

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(audit_logs.router)
api_router.include_router(processing.router)
api_router.include_router(tickets.router)
api_router.include_router(customers.router)
api_router.include_router(sla.router)
