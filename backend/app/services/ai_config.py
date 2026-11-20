"""AI runtime settings (AI management): on/off switch, models per step, and spending caps.

Stored in `system_configurations` under `ai.*` keys, separate from the general runtime settings so the
Settings screen's number table is unaffected. Every change is audited. Credentials are NOT settings:
the OpenRouter key comes only from the environment.

Budget guard: before every model call the pipeline checks today's spend (IST calendar day, measured
from `model_usage`) against the daily cap, and the ticket's spend against the per-ticket cap. When a cap
is reached the call is not made and the ticket goes to a person.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import LLMProvider
from app.core.config import Settings
from app.models.processing import ModelUsage
from app.models.settings import SystemConfiguration
from app.services import audit
from app.services.normalization.timestamps import IST

MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]{0,100}$")


@dataclass(frozen=True)
class AiKey:
    key: str
    label: str
    kind: str  # bool | float | model
    default: Any
    minimum: float | None = None
    maximum: float | None = None


AI_SPECS: dict[str, AiKey] = {
    s.key: s
    for s in (
        AiKey("ai.enabled", "Use the AI model for classification and drafting", "bool", False),
        AiKey("ai.classifier_model", "Model for ticket classification", "model", None),
        AiKey("ai.drafting_model", "Model for draft replies", "model", None),
        AiKey("ai.daily_budget_usd", "Daily AI spending cap (USD, IST day)", "float", 2.0, 0.1, 100.0),
        AiKey("ai.ticket_budget_usd", "AI spending cap per ticket (USD)", "float", 0.05, 0.001, 1.0),
    )
}


class AiConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AiConfig:
    enabled: bool
    classifier_model: str | None
    drafting_model: str | None
    daily_budget_usd: Decimal
    ticket_budget_usd: Decimal
    provider: str  # from deployment configuration
    key_configured: bool

    @property
    def ready(self) -> bool:
        return self.enabled and self.provider == "openrouter" and self.key_configured


def _coerce(spec: AiKey, value: Any) -> Any:
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise AiConfigError(f"{spec.key} must be true or false")
        return value
    if spec.kind == "model":
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not MODEL_ID.fullmatch(value.strip()):
            raise AiConfigError(f"{spec.key} must be an OpenRouter model id such as vendor/model-name")
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AiConfigError(f"{spec.key} must be a number")
    number = float(value)
    if (spec.minimum is not None and number < spec.minimum) or (spec.maximum is not None and number > spec.maximum):
        raise AiConfigError(f"{spec.key} must be between {spec.minimum} and {spec.maximum}")
    return number


async def _stored(session: AsyncSession) -> dict[str, SystemConfiguration]:
    rows = await session.scalars(select(SystemConfiguration).where(SystemConfiguration.key.like("ai.%")))
    return {r.key: r for r in rows}


async def values(session: AsyncSession) -> dict[str, Any]:
    out = {k: s.default for k, s in AI_SPECS.items()}
    for key, row in (await _stored(session)).items():
        if key in AI_SPECS:
            out[key] = row.value
    return out


async def load(session: AsyncSession, settings: Settings) -> AiConfig:
    v = await values(session)
    return AiConfig(
        enabled=bool(v["ai.enabled"]),
        classifier_model=v["ai.classifier_model"],
        drafting_model=v["ai.drafting_model"],
        daily_budget_usd=Decimal(str(v["ai.daily_budget_usd"])),
        ticket_budget_usd=Decimal(str(v["ai.ticket_budget_usd"])),
        provider=settings.llm_provider,
        key_configured=bool(settings.openrouter_api_key and settings.openrouter_api_key.get_secret_value()),
    )


async def update(session: AsyncSession, changes: dict[str, Any], actor: uuid.UUID) -> dict[str, Any]:
    unknown = sorted(set(changes) - set(AI_SPECS))
    if unknown:
        raise AiConfigError(f"Unknown AI settings: {unknown}")
    current = await values(session)
    rows = await _stored(session)
    applied: dict[str, dict[str, Any]] = {}
    for key, raw in changes.items():
        value = _coerce(AI_SPECS[key], raw)
        if value == current[key]:
            continue
        if value is None:  # cleared model: back to "not configured"
            if key in rows:
                await session.delete(rows[key])
        elif key in rows:
            rows[key].value, rows[key].updated_by = value, actor
        else:
            session.add(SystemConfiguration(key=key, value=value, updated_by=actor))
        applied[key] = {"from": current[key], "to": value}
    if applied:
        await audit.record(session, "ai_settings.updated", actor_user_id=actor, entity_type="settings", details=applied)
    return applied


def build_provider(settings: Settings, model: str | None) -> LLMProvider | None:
    """OpenRouter provider for one model, or None when not configured (the step then goes to a person)."""
    if settings.llm_provider != "openrouter" or not model or not settings.openrouter_api_key:
        return None
    key = settings.openrouter_api_key.get_secret_value()
    if not key:
        return None
    from app.ai.providers.openrouter import OpenRouterLLM

    return OpenRouterLLM(
        key, model, base_url=settings.openrouter_base_url, timeout_seconds=settings.openrouter_timeout_seconds
    )


# ----------------------------------------------------------------------------------------- budget guard
def ist_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    day = now.astimezone(IST).date()
    start = datetime.combine(day, time.min, tzinfo=IST)
    return start, start + timedelta(days=1)


async def spent_today(session: AsyncSession, now: datetime) -> Decimal:
    start, end = ist_day_bounds(now)
    total = await session.scalar(
        select(func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0)).where(
            ModelUsage.created_at >= start, ModelUsage.created_at < end
        )
    )
    return Decimal(str(total or 0))


async def spent_on_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0)).where(ModelUsage.ticket_id == ticket_id)
    )
    return Decimal(str(total or 0))


async def budget_block(session: AsyncSession, cfg: AiConfig, ticket_id: uuid.UUID, now: datetime) -> str | None:
    """Returns why a model call must not be made (cap reached), or None when it may proceed."""
    if await spent_today(session, now) >= cfg.daily_budget_usd:
        return "daily_budget_reached"
    if await spent_on_ticket(session, ticket_id) >= cfg.ticket_budget_usd:
        return "ticket_budget_reached"
    return None
