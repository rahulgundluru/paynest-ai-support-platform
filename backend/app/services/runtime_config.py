"""Runtime configuration: typed, bounded keys with defaults; stored values override defaults.

Only keys declared here can be changed, only within their bounds, and every change is audited.
Services read the effective values through `load_runtime_config` so a change takes effect on the
next routing / detection / classification run without a redeploy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemConfiguration
from app.services import audit
from app.services.deduplication.detector import DedupeConfig
from app.services.routing.engine import RoutingConfig


@dataclass(frozen=True)
class KeySpec:
    key: str
    label: str
    kind: str  # float | int | bool
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    editable: bool = True
    locked_reason: str | None = None


SPECS: dict[str, KeySpec] = {
    s.key: s
    for s in (
        KeySpec(
            "classification.confidence_threshold", "Classifier confidence below which a person decides", "float",
            0.80, 0.5, 0.99,
        ),
        KeySpec("dedupe.incident_min_tickets", "Tickets from one customer that make an incident", "int", 5, 3, 20),
        KeySpec("dedupe.incident_gap_hours", "Maximum gap between incident tickets (hours)", "float", 3.0, 0.5, 24.0),
        KeySpec("dedupe.follow_up_window_days", "How far back a follow-up can point (days)", "int", 7, 1, 30),
        KeySpec(
            "routing.auto_answer_enabled", "Send cited How-To answers without an agent", "bool", False,
            editable=False, locked_reason="Locked until two weeks of shadow-mode evaluation (Phase 6) show it is safe.",
        ),
    )
}  # fmt: skip


class ConfigError(ValueError):
    pass


def coerce(spec: KeySpec, value: Any) -> Any:
    if not spec.editable:
        raise ConfigError(f"{spec.key} is locked: {spec.locked_reason}")
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError(f"{spec.key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{spec.key} must be a number")
    number = int(value) if spec.kind == "int" else float(value)
    if spec.kind == "int" and number != value:
        raise ConfigError(f"{spec.key} must be a whole number")
    if (spec.minimum is not None and number < spec.minimum) or (spec.maximum is not None and number > spec.maximum):
        raise ConfigError(f"{spec.key} must be between {spec.minimum} and {spec.maximum}")
    return number


async def stored(session: AsyncSession) -> dict[str, SystemConfiguration]:
    return {c.key: c for c in await session.scalars(select(SystemConfiguration))}


async def effective(session: AsyncSession) -> dict[str, Any]:
    values = {k: s.default for k, s in SPECS.items()}
    for key, row in (await stored(session)).items():
        if key in SPECS and SPECS[key].editable:
            values[key] = row.value
    return values


async def load_runtime_config(session: AsyncSession) -> tuple[RoutingConfig, DedupeConfig]:
    v = await effective(session)
    return (
        RoutingConfig(
            confidence_threshold=float(v["classification.confidence_threshold"]),
            auto_answer_enabled=bool(v["routing.auto_answer_enabled"]),
        ),
        DedupeConfig(
            follow_up_window=timedelta(days=int(v["dedupe.follow_up_window_days"])),
            incident_min_tickets=int(v["dedupe.incident_min_tickets"]),
            incident_gap=timedelta(hours=float(v["dedupe.incident_gap_hours"])),
        ),
    )


async def update(session: AsyncSession, changes: dict[str, Any], actor: uuid.UUID) -> dict[str, Any]:
    unknown = sorted(set(changes) - set(SPECS))
    if unknown:
        raise ConfigError(f"Unknown settings: {unknown}")
    current = await effective(session)
    rows = await stored(session)
    applied: dict[str, dict[str, Any]] = {}
    for key, raw in changes.items():
        value = coerce(SPECS[key], raw)
        if value == current[key]:
            continue
        if key in rows:
            rows[key].value, rows[key].updated_by = value, actor
        else:
            session.add(SystemConfiguration(key=key, value=value, updated_by=actor))
        applied[key] = {"from": current[key], "to": value}
    if applied:
        await audit.record(session, "settings.updated", actor_user_id=actor, entity_type="settings", details=applied)
    return applied
