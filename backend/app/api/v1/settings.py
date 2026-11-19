"""System configuration. Returns only non-secret values; credentials are never readable through the API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.ai.prompts.classification import PROMPT_VERSION
from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.core.rbac import ROLE_PERMISSIONS, Permission
from app.models.reference import SlaTerm
from app.services import runtime_config
from app.services.deduplication.detector import RULESET_VERSION as DEDUPE_VERSION
from app.services.normalization.rules import RULESET_VERSION as NORMALIZATION_VERSION
from app.services.routing.engine import RULES, RULESET_VERSION
from app.services.sla.engine import RULE_VERSION as SLA_VERSION
from app.services.validation.output import VALIDATOR_VERSION

router = APIRouter(prefix="/settings", tags=["settings"])


async def _view(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    values = await runtime_config.effective(session)
    rows = await runtime_config.stored(session)
    terms = await session.scalars(select(SlaTerm).order_by(SlaTerm.tier, SlaTerm.priority))
    return {
        "runtime": [
            {
                "key": spec.key,
                "label": spec.label,
                "kind": spec.kind,
                "value": values[spec.key],
                "default": spec.default,
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "editable": spec.editable,
                "locked_reason": spec.locked_reason,
                "updated_at": rows[spec.key].updated_at.isoformat() if spec.key in rows else None,
            }
            for spec in runtime_config.SPECS.values()
        ],
        "models": {
            "llm_provider": settings.llm_provider,
            "classifier_model_id": settings.bedrock_classifier_model_id or "not configured",
            "embedding_provider": settings.embedding_provider,
            "embedding_model_id": settings.bedrock_embedding_model_id or "not configured",
            "region": settings.bedrock_region,
            "credentials": "AWS default credential chain (IAM role in AWS); never stored or displayed here",
            "change_process": "Deployment configuration (environment / Secrets Manager); not editable here.",
        },
        "privacy": {
            "pii_retention_days": settings.pii_retention_days,
            "retention_note": "Pending the DPO's retention decision; deployment configuration.",
            "vault_key": "configured" if settings.pii_vault_key.get_secret_value() else "missing",
        },
        "routing_rules": [{"rule_id": r, "lane": lane, "description": d} for r, lane, d in RULES],
        "sla_terms": [
            {
                "template_version": t.template_version,
                "tier": t.tier,
                "priority": t.priority,
                "first_response_h": str(t.first_response_h),
                "resolution_h": str(t.resolution_h),
                "credit_pct": str(t.credit_pct),
            }
            for t in terms
        ],
        "regions": [
            {"code": "IN", "name": "India", "data_residency": "India (DPDP Act)"},
            {"code": "UAE", "name": "United Arab Emirates", "data_residency": "UAE (PDPL)"},
        ],
        "roles": {role.value: sorted(p.value for p in perms) for role, perms in ROLE_PERMISSIONS.items()},
        "versions": {
            "routing_ruleset": RULESET_VERSION,
            "dedupe_ruleset": DEDUPE_VERSION,
            "normalization_ruleset": NORMALIZATION_VERSION,
            "sla_rules": SLA_VERSION,
            "output_validator": VALIDATOR_VERSION,
            "classification_prompt": PROMPT_VERSION,
        },
    }


@router.get("")
async def get_settings(
    session: SessionDep, settings: SettingsDep, _: Annotated[Principal, Depends(require(Permission.SETTINGS_READ))]
) -> dict[str, Any]:
    return await _view(session, settings)


@router.patch("")
async def patch_settings(
    body: dict[str, Any],
    session: SessionDep,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require(Permission.SETTINGS_MANAGE))],
) -> dict[str, Any]:
    """Change runtime settings, e.g. {"dedupe.incident_min_tickets": 6}. Bounded, typed and audited."""
    try:
        applied = await runtime_config.update(session, body, principal.user.id)
    except runtime_config.ConfigError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"applied": applied, "settings": await _view(session, settings)}
