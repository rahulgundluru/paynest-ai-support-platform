from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.core.rbac import Permission
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.schemas.common import Page
from app.services.evaluation.gates import ALL_GATES
from app.services.evaluation.runner import run_gates

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
Reader = Annotated[Principal, Depends(require(Permission.EVALUATIONS_READ))]


def _run_out(r: EvaluationRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "gate": r.gate,
        "name": r.name,
        "status": r.status,
        "dataset": r.dataset,
        "dataset_size": r.dataset_size,
        "target": r.target,
        "metrics": r.metrics,
        "notes": r.notes,
        "critical": r.critical,
        "source_commit": r.source_commit,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


class RunRequest(BaseModel):
    gates: list[str] = Field(default_factory=lambda: list(ALL_GATES))


@router.post("/run")
async def run(
    body: RunRequest,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(Permission.EVALUATIONS_RUN))],
) -> list[dict[str, Any]]:
    gates = [g.upper() for g in body.gates]
    unknown = sorted(set(gates) - set(ALL_GATES))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown gates: {unknown}")
    return [_run_out(r) for r in await run_gates(gates, settings, principal.user.id)]


@router.get("/gates")
async def gates(session: SessionDep, _: Reader) -> list[dict[str, Any]]:
    """Latest run per gate with its recent history (newest first)."""
    out: list[dict[str, Any]] = []
    for gate in ALL_GATES:
        runs = list(
            await session.scalars(
                select(EvaluationRun)
                .where(EvaluationRun.gate == gate)
                .order_by(EvaluationRun.started_at.desc())
                .limit(10)
            )
        )
        latest = runs[0] if runs else None
        failed = 0
        if latest:
            failed = (
                await session.scalar(
                    select(func.count()).where(EvaluationResult.run_id == latest.id, EvaluationResult.passed.is_(False))
                )
                or 0
            )
        out.append(
            {
                "gate": gate,
                "latest": _run_out(latest) if latest else None,
                "failed_cases": failed,
                "history": [
                    {"id": str(r.id), "status": r.status, "started_at": r.started_at.isoformat()} for r in runs
                ],
            }
        )
    return out


@router.get("", response_model=Page[dict[str, Any]])
async def list_runs(
    session: SessionDep,
    _: Reader,
    gate: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[dict[str, Any]]:
    query = select(EvaluationRun)
    if gate:
        query = query.where(EvaluationRun.gate == gate.upper())
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(EvaluationRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[dict[str, Any]](items=[_run_out(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: SessionDep, _: Reader) -> dict[str, Any]:
    run = await session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    results = await session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run.id)
        .order_by(EvaluationResult.passed, EvaluationResult.id)
    )
    return {
        **_run_out(run),
        "cases": [{"case_id": r.case_id, "passed": r.passed, "detail": r.detail} for r in results],
    }
