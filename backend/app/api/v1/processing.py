from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.core.rbac import Permission
from app.models.tickets import IngestionBatch
from app.schemas.common import Page
from app.schemas.tickets import IngestionBatchOut
from app.services.ingestion.pipeline import SourceDataMissing, run_ingestion

router = APIRouter(prefix="/processing", tags=["processing"])


@router.post("/ingest", response_model=IngestionBatchOut)
async def ingest(
    session: SessionDep,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(Permission.INGESTION_RUN))],
) -> IngestionBatchOut:
    """Ingest the pinned source exports (tickets, WhatsApp, calls) plus reference data. Idempotent."""
    try:
        batch = await run_ingestion(
            session,
            Path(settings.data_source_dir),
            triggered_by=principal.user.id,
            retention_days=settings.pii_retention_days,
        )
    except SourceDataMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return IngestionBatchOut.model_validate(batch)


@router.get("/batches", response_model=Page[IngestionBatchOut])
async def list_batches(
    session: SessionDep,
    _: Annotated[Principal, Depends(require(Permission.INGESTION_READ))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[IngestionBatchOut]:
    total = await session.scalar(select(func.count()).select_from(IngestionBatch)) or 0
    rows = await session.scalars(
        select(IngestionBatch)
        .order_by(IngestionBatch.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page[IngestionBatchOut](
        items=[IngestionBatchOut.model_validate(b) for b in rows], total=total, page=page, page_size=page_size
    )


@router.get("/batches/{batch_id}", response_model=IngestionBatchOut)
async def get_batch(
    batch_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[Principal, Depends(require(Permission.INGESTION_READ))],
) -> IngestionBatchOut:
    batch = await session.get(IngestionBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return IngestionBatchOut.model_validate(batch)
