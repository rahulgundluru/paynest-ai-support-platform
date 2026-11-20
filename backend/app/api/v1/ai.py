"""AI management: what the model costs, how it behaves, and how it is configured.

Every number here is computed from `model_usage` (one row per model call, with the cost the provider
reported) and `pipeline_runs`. Nothing is estimated except the clearly labelled monthly projection,
which multiplies the MEASURED average cost per ticket by the Finance cost sheet's ticket volume.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select, text

from app.ai.prompts import classification as classify_prompt
from app.ai.providers.base import PiiLeakBlocked, ProviderUnavailable
from app.ai.providers.openrouter import PRIVACY, fetch_key_info, fetch_models
from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.api.scoping import region_filter
from app.api.v1.processing_ai import _ticket
from app.core.rbac import Permission
from app.models.evaluation import MonthlyCost
from app.models.processing import ModelUsage, PipelineRun
from app.models.tickets import Ticket
from app.schemas.common import Page
from app.services import ai_config, audit
from app.services.ai_config import AI_SPECS, AiConfigError
from app.services.normalization.timestamps import IST

router = APIRouter(prefix="/ai", tags=["ai"])
Viewer = Annotated[Principal, Depends(require(Permission.AI_READ))]
Manager = Annotated[Principal, Depends(require(Permission.AI_MANAGE))]
BUDGET_CAP_USD = Decimal("4500")  # monthly AI + hosting + search budget (business constraint)
_MODELS_CACHE: dict[str, Any] = {"at": 0.0, "items": []}


def _f(value: Any) -> float:
    return float(value or 0)


def _status(cfg: ai_config.AiConfig) -> dict[str, Any]:
    if cfg.provider != "openrouter":
        state, note = "not_configured", "LLM_PROVIDER is not 'openrouter' in the server configuration"
    elif not cfg.key_configured:
        state, note = "no_key", "OPENROUTER_API_KEY is not set on the server"
    elif not cfg.enabled:
        state, note = "off", "AI is switched off; tickets use the customer's category and agents write replies"
    elif not cfg.classifier_model and not cfg.drafting_model:
        state, note = "no_model", "Select a classification and a drafting model"
    else:
        state, note = "on", "AI steps run for new tickets and re-runs"
    return {
        "state": state,
        "note": note,
        "provider": cfg.provider,
        "key_configured": cfg.key_configured,
        "enabled": cfg.enabled,
        "classifier_model": cfg.classifier_model,
        "drafting_model": cfg.drafting_model,
        "daily_budget_usd": float(cfg.daily_budget_usd),
        "ticket_budget_usd": float(cfg.ticket_budget_usd),
        "privacy": {**PRIVACY, "note": "Masked text only; providers that neither collect nor retain prompts. "
                    "Approved for the synthetic case data; real customer data needs DPO sign-off."},
    }  # fmt: skip


@router.get("/status")
async def ai_status(
    session: SessionDep, settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(Permission.TICKETS_READ))],
) -> dict[str, Any]:  # fmt: skip
    """Whether AI steps will run (for the New ticket screen). No spend figures."""
    s = _status(await ai_config.load(session, settings))
    return {k: s[k] for k in ("state", "note", "enabled", "classifier_model", "drafting_model")}


@router.get("/overview")
async def overview(
    session: SessionDep, settings: SettingsDep, principal: Viewer,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> dict[str, Any]:  # fmt: skip
    cfg = await ai_config.load(session, settings)
    now = datetime.now(tz=UTC)
    day_start, _ = ai_config.ist_day_bounds(now)
    month_start = day_start.replace(day=1)
    since = day_start - timedelta(days=days - 1)
    mu = ModelUsage
    cost = func.coalesce(func.sum(mu.estimated_cost_usd), 0)

    async def window(start: datetime) -> dict[str, Any]:
        row = (
            await session.execute(
                select(func.count(), func.count().filter(mu.success), cost, func.count(distinct(mu.ticket_id)))
                .where(mu.created_at >= start)
            )
        ).one()  # fmt: skip
        return {"calls": row[0], "successful": row[1], "cost_usd": _f(row[2]), "tickets": row[3]}

    today, month, period = await window(day_start), await window(month_start), await window(since)
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(mu.input_tokens), 0), func.coalesce(func.sum(mu.output_tokens), 0),
                func.percentile_cont(0.5).within_group(mu.latency_ms).filter(mu.success),
                func.percentile_cont(0.95).within_group(mu.latency_ms).filter(mu.success),
                func.count().filter(mu.cost_source == "provider_reported"),
            ).where(mu.created_at >= since)
        )
    ).one()  # fmt: skip

    # IST has no daylight saving, so a fixed +05:30 offset is exact (and needs no tz database).
    day_col = func.date(func.timezone("UTC", mu.created_at) + timedelta(hours=5, minutes=30))
    by_day_rows = {
        r[0]: r
        for r in (
            await session.execute(
                select(day_col, func.count(), func.count().filter(~mu.success), cost)
                .where(mu.created_at >= since).group_by(day_col)
            )
        ).all()
    }  # fmt: skip
    first_day = since.astimezone(IST).date()
    by_day = []
    for i in range(days):
        d: date = first_day + timedelta(days=i)
        r = by_day_rows.get(d)
        by_day.append({"date": d.isoformat(), "calls": r[1] if r else 0, "failed": r[2] if r else 0,
                       "cost_usd": _f(r[3]) if r else 0.0})  # fmt: skip

    by_model = [
        {
            "model": r[0], "operation": r[1], "calls": r[2], "successful": r[3], "cost_usd": _f(r[4]),
            "input_tokens": int(r[5] or 0), "output_tokens": int(r[6] or 0),
            "latency_ms_p50": round(_f(r[7])), "latency_ms_p95": round(_f(r[8])),
            "avg_cost_usd": _f(r[4]) / r[3] if r[3] else None,
        }
        for r in (
            await session.execute(
                select(
                    mu.model, mu.operation, func.count(), func.count().filter(mu.success), cost,
                    func.sum(mu.input_tokens), func.sum(mu.output_tokens),
                    func.percentile_cont(0.5).within_group(mu.latency_ms).filter(mu.success),
                    func.percentile_cont(0.95).within_group(mu.latency_ms).filter(mu.success),
                )
                .where(mu.created_at >= since).group_by(mu.model, mu.operation).order_by(cost.desc())
            )
        ).all()
    ]  # fmt: skip

    per_ticket = (
        await session.execute(
            text(
                "SELECT avg(c), max(c), count(*) FROM (SELECT ticket_id, sum(estimated_cost_usd) c FROM model_usage "
                "WHERE ticket_id IS NOT NULL AND created_at >= :since AND estimated_cost_usd IS NOT NULL "
                "GROUP BY ticket_id) t"
            ),
            {"since": since},
        )
    ).one()
    per_draft = await session.scalar(
        select(func.avg(mu.estimated_cost_usd)).where(mu.operation == "draft", mu.success, mu.created_at >= since)
    )
    errors = {
        str(r[0]): r[1]
        for r in (
            await session.execute(
                select(mu.error, func.count()).where(mu.error.is_not(None), mu.created_at >= since).group_by(mu.error)
            )
        ).all()
    }

    step_reason = text(
        "SELECT s->>'key' AS step, s->'details'->>'reason' AS reason, count(*) FROM pipeline_runs r, "
        "jsonb_array_elements(r.steps) s WHERE r.started_at >= :since AND s->>'status' = 'skipped' "
        "AND s->'details'->>'reason' IS NOT NULL GROUP BY 1, 2"
    )
    skipped = [
        {"step": r[0], "reason": r[1], "count": r[2]}
        for r in (await session.execute(step_reason, {"since": since})).all()
    ]
    guardrails = {
        "pii_blocked_calls": errors.get("pii_blocked", 0),
        "schema_failures": errors.get("schema_validation_failed", 0),
        "provider_errors": {k: v for k, v in errors.items() if k not in ("pii_blocked", "schema_validation_failed")},
        "budget_stops": sum(s["count"] for s in skipped if s["reason"] and "budget" in s["reason"]),
        "injection_skips": sum(s["count"] for s in skipped if s["reason"] == "injection_screen"),
        "skipped_steps": skipped,
    }
    validation = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE s->>'status' = 'done'), count(*) FILTER (WHERE s->>'status' = 'failed') "
                "FROM pipeline_runs r, jsonb_array_elements(r.steps) s WHERE r.started_at >= :since "
                "AND s->>'key' = 'validation'"
            ),
            {"since": since},
        )
    ).one()
    runs = (
        await session.execute(
            select(
                func.count(), func.count().filter(PipelineRun.status == "completed"),
                func.count().filter(PipelineRun.status == "failed"),
                func.avg(func.extract("epoch", PipelineRun.finished_at - PipelineRun.started_at)),
                func.avg(PipelineRun.total_cost_usd).filter(PipelineRun.status == "completed"),
            ).where(PipelineRun.started_at >= since)
        )
    ).one()  # fmt: skip

    volume = await session.scalar(
        select(func.avg(MonthlyCost.tickets_received_all_customers)).where(MonthlyCost.month >= "2026-07")
    )
    avg_ticket = Decimal(str(per_ticket[0])) if per_ticket[0] is not None else None
    projection = None
    if avg_ticket is not None and volume:
        monthly = avg_ticket * Decimal(str(volume))
        projection = {
            "avg_cost_per_ticket_usd": float(avg_ticket),
            "tickets_per_month": round(float(volume)),
            "monthly_model_cost_usd": float(monthly),
            "budget_cap_usd": float(BUDGET_CAP_USD),
            "share_of_cap": float(monthly / BUDGET_CAP_USD),
            "basis": "measured average AI cost per ticket in this window × Finance cost sheet volume (Jul–Sep "
            "2026 average); hosting and search are not included",
            "sample_tickets": per_ticket[2],
        }
    top = [
        {"ticket": r[0], "cost_usd": _f(r[1]), "calls": r[2]}
        for r in (
            await session.execute(
                select(Ticket.external_id, cost, func.count())
                .join(Ticket, Ticket.id == mu.ticket_id)
                .where(mu.created_at >= since, region_filter(principal, Ticket.region))
                .group_by(Ticket.external_id).order_by(cost.desc()).limit(8)
            )
        ).all()
    ]  # fmt: skip
    return {
        "status": _status(cfg),
        "window_days": days,
        "today": {**today, "budget_usd": float(cfg.daily_budget_usd),
                  "budget_remaining_usd": max(0.0, float(cfg.daily_budget_usd) - today["cost_usd"])},
        "month": month,
        "period": {
            **period,
            "input_tokens": int(totals[0]), "output_tokens": int(totals[1]),
            "latency_ms_p50": round(_f(totals[2])), "latency_ms_p95": round(_f(totals[3])),
            "provider_reported_cost_calls": totals[4],
            "avg_cost_per_ticket_usd": float(avg_ticket) if avg_ticket is not None else None,
            "max_cost_per_ticket_usd": _f(per_ticket[1]) if per_ticket[1] is not None else None,
            "avg_cost_per_draft_usd": _f(per_draft) if per_draft is not None else None,
            "draft_target_usd": 0.02,
        },
        "by_day": by_day,
        "by_model": by_model,
        "guardrails": {**guardrails, "drafts_passed_validation": validation[0],
                       "drafts_failed_validation": validation[1]},
        "runs": {"total": runs[0], "completed": runs[1], "failed": runs[2],
                 "avg_duration_s": round(_f(runs[3]), 2) if runs[3] is not None else None,
                 "avg_cost_usd": _f(runs[4]) if runs[4] is not None else None},
        "projection": projection,
        "top_tickets": top,
    }  # fmt: skip


@router.get("/calls")
async def calls(
    session: SessionDep, principal: Viewer,
    operation: Literal["classify", "draft", "embed", "judge"] | None = None,
    outcome: Literal["success", "failed"] | None = None,
    model: str | None = None,
    ticket: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[dict[str, Any]]:  # fmt: skip
    mu = ModelUsage
    query = (
        select(mu, Ticket.external_id)
        .outerjoin(Ticket, Ticket.id == mu.ticket_id)
        .where(region_filter(principal, Ticket.region) | mu.ticket_id.is_(None))
    )
    if operation:
        query = query.where(mu.operation == operation)
    if outcome:
        query = query.where(mu.success.is_(outcome == "success"))
    if model:
        query = query.where(mu.model == model)
    if ticket:
        query = query.where(Ticket.external_id == ticket.strip().upper())
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.execute(query.order_by(mu.created_at.desc(), mu.id.desc())
                                  .offset((page - 1) * page_size).limit(page_size))).all()  # fmt: skip
    items = [
        {
            "id": m.id, "created_at": m.created_at.isoformat(), "ticket": ref, "operation": m.operation,
            "provider": m.provider, "upstream_provider": m.upstream_provider, "model": m.model,
            "prompt_version": m.prompt_version, "input_tokens": m.input_tokens, "output_tokens": m.output_tokens,
            "latency_ms": m.latency_ms,
            "cost_usd": float(m.estimated_cost_usd) if m.estimated_cost_usd is not None else None,
            "cost_source": m.cost_source, "success": m.success, "error": m.error,
            "pipeline_run_id": str(m.pipeline_run_id) if m.pipeline_run_id else None,
        }
        for m, ref in rows
    ]  # fmt: skip
    return Page[dict[str, Any]](items=items, total=total, page=page, page_size=page_size)


@router.get("/tickets/{ref}/cost")
async def ticket_cost(ref: str, session: SessionDep, principal: Annotated[Principal, Depends(
        require(Permission.TICKETS_READ))]) -> dict[str, Any]:  # fmt: skip
    """AI cost of one ticket, by step and by run. Visible to anyone who can read the ticket."""
    t = await _ticket(session, principal, ref)
    mu = ModelUsage
    ops = [
        {"operation": r[0], "calls": r[1], "successful": r[2], "cost_usd": _f(r[3]), "input_tokens": int(r[4] or 0),
         "output_tokens": int(r[5] or 0), "latency_ms": int(r[6] or 0)}
        for r in (
            await session.execute(
                select(mu.operation, func.count(), func.count().filter(mu.success),
                       func.coalesce(func.sum(mu.estimated_cost_usd), 0), func.sum(mu.input_tokens),
                       func.sum(mu.output_tokens), func.sum(mu.latency_ms))
                .where(mu.ticket_id == t.id).group_by(mu.operation)
            )
        ).all()
    ]  # fmt: skip
    runs = list(
        await session.scalars(
            select(PipelineRun).where(PipelineRun.ticket_id == t.id).order_by(PipelineRun.started_at.desc()).limit(10)
        )
    )
    return {
        "ticket": t.external_id,
        "total_cost_usd": sum(o["cost_usd"] for o in ops),
        "calls": sum(o["calls"] for o in ops),
        "by_operation": ops,
        "runs": [
            {"id": str(r.id), "trigger": r.trigger, "status": r.status, "started_at": r.started_at.isoformat(),
             "cost_usd": float(r.total_cost_usd)}
            for r in runs
        ],
        "draft_target_usd": 0.02,
    }  # fmt: skip


class AiConfigPatch(BaseModel):
    changes: dict[str, Any]


@router.get("/config")
async def get_config(session: SessionDep, settings: SettingsDep, principal: Viewer) -> dict[str, Any]:
    cfg = await ai_config.load(session, settings)
    values = await ai_config.values(session)
    return {
        "status": _status(cfg),
        "settings": [
            {"key": s.key, "label": s.label, "kind": s.kind, "value": values[s.key], "default": s.default,
             "minimum": s.minimum, "maximum": s.maximum}
            for s in AI_SPECS.values()
        ],
        "can_manage": Permission.AI_MANAGE in principal.permissions,
        "credentials": "The OpenRouter API key is deployment configuration (environment); never stored or shown here.",
    }  # fmt: skip


@router.patch("/config")
async def patch_config(
    body: AiConfigPatch, session: SessionDep, settings: SettingsDep, principal: Manager
) -> dict[str, Any]:
    try:
        applied = await ai_config.update(session, body.changes, principal.user.id)
    except AiConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"applied": applied, **(await get_config(session, settings, principal))}


@router.get("/models")
async def models(settings: SettingsDep, principal: Viewer, refresh: bool = False) -> dict[str, Any]:
    """OpenRouter's public model catalogue (tool-calling models only), cheapest first. Cached for 1 hour."""
    if refresh or not _MODELS_CACHE["items"] or time.monotonic() - _MODELS_CACHE["at"] > 3600:
        try:
            _MODELS_CACHE["items"] = await fetch_models(settings.openrouter_base_url)
            _MODELS_CACHE["at"] = time.monotonic()
        except (ProviderUnavailable, OSError) as exc:
            if not _MODELS_CACHE["items"]:
                raise HTTPException(status_code=502, detail=f"Could not load the model list: {exc}") from None
    return {"items": _MODELS_CACHE["items"], "source": "openrouter.ai/api/v1/models", "prices": "USD per 1M tokens"}


@router.get("/account")
async def account(settings: SettingsDep, principal: Manager) -> dict[str, Any]:
    """Spend and limit OpenRouter reports for the configured key (admin only)."""
    if not settings.openrouter_api_key or not settings.openrouter_api_key.get_secret_value():
        raise HTTPException(status_code=409, detail="No OpenRouter API key is configured on the server")
    try:
        return await fetch_key_info(settings.openrouter_api_key.get_secret_value(), settings.openrouter_base_url)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"{exc} ({exc.code})") from None


@router.post("/test")
async def test_connection(session: SessionDep, settings: SettingsDep, principal: Manager) -> dict[str, Any]:
    """One tiny synthetic classification call to the selected classifier model. It is billed and recorded."""
    cfg = await ai_config.load(session, settings)
    provider = ai_config.build_provider(settings, cfg.classifier_model)
    if provider is None:
        raise HTTPException(status_code=409, detail=_status(cfg)["note"])
    started = time.perf_counter()
    user = classify_prompt.user_message("email", "how_to", "Where do I download payslips?",
                                        "Hi, where can employees download their payslips for last month?")  # fmt: skip
    try:
        result = await provider.structured(
            system=classify_prompt.SYSTEM, user=user, tool_name=classify_prompt.TOOL_NAME,
            tool_description=classify_prompt.TOOL_DESCRIPTION, schema=classify_prompt.SCHEMA, max_tokens=300,
        )  # fmt: skip
    except (ProviderUnavailable, PiiLeakBlocked, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        session.add(ModelUsage(provider="openrouter", model=cfg.classifier_model or "unknown", operation="classify",
                               prompt_version="connection-test", latency_ms=int((time.perf_counter() - started) * 1000),
                               success=False, error=str(code)[:40]))  # fmt: skip
        await session.commit()
        return {"ok": False, "error": str(exc), "code": code}
    session.add(
        ModelUsage(provider="openrouter", model=result.model, operation="classify", prompt_version="connection-test",
                   input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                   latency_ms=result.latency_ms, estimated_cost_usd=result.cost_usd,
                   cost_source="provider_reported" if result.cost_usd is not None else None, success=True,
                   request_id=result.request_id, upstream_provider=result.upstream_provider)
    )  # fmt: skip
    await audit.record(session, "ai.connection_tested", actor_user_id=principal.user.id,
                       details={"model": result.model, "ok": True})  # fmt: skip
    await session.commit()
    return {
        "ok": True, "model": result.model, "upstream_provider": result.upstream_provider,
        "latency_ms": result.latency_ms, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "cost_usd": float(result.cost_usd) if result.cost_usd is not None else None,
        "category": result.data.get("category"), "confidence": result.data.get("confidence"),
    }  # fmt: skip
