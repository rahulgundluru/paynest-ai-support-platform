"""Ticket classification: typed model output + deterministic safeguards + human fallback.

- Input is redacted text and the customer's original pick. The export's final category label is
  never sent (it is the answer key for evaluation).
- Output is validated with Pydantic; invalid output is retried once, then recorded as `invalid`.
- No provider configured => status `unavailable`, requires_human=True. Nothing is guessed.
- A rule-based injection screen runs regardless of the model (defence in depth, G4).
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import classification as prompt
from app.ai.providers.base import LLMProvider, PiiLeakBlocked, ProviderUnavailable
from app.core.config import Settings
from app.models.processing import Classification, ModelUsage
from app.models.tickets import Ticket

_INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (all |any )?(previous|prior|above|your) (instructions|rules)",
    r"you are now (in )?(admin|developer|god|dan) mode",
    r"(reveal|show|print|repeat) (your|the) (system )?(prompt|instructions)",
    r"mark (refund|invoice|payment)\b.*\b(approved|paid)",
    r"(list|send|give) (me )?(of )?all customer",
    r"do not mention this (message|instruction)",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


def injection_signals(*texts: str | None) -> list[str]:
    """Deterministic screen for instructions aimed at an AI. Returns the matched phrases (redacted text only)."""
    return [m.group(0) for t in texts if t for m in _INJECTION.finditer(t)]


class ClassificationOutput(BaseModel):
    category: Literal[
        "payroll", "statutory", "how_to", "reports", "leave_attendance",
        "integration", "billing", "access_login", "onboarding",
    ]  # fmt: skip
    subcategory: str = Field(max_length=80)
    intent: str = Field(max_length=120)
    priority: Literal["P1", "P2", "P3"]
    language: Literal["en", "hi", "hinglish", "ar", "other"]
    is_injection: bool
    requires_human: bool
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=300)


def _cost(settings: Settings, input_tokens: int, output_tokens: int) -> Decimal | None:
    if settings.classifier_input_usd_per_mtok is None or settings.classifier_output_usd_per_mtok is None:
        return None
    return Decimal(
        str(
            input_tokens / 1e6 * settings.classifier_input_usd_per_mtok
            + output_tokens / 1e6 * settings.classifier_output_usd_per_mtok
        )
    )


async def classify_ticket(
    session: AsyncSession, ticket: Ticket, provider: LLMProvider | None, settings: Settings
) -> Classification:
    heuristics = injection_signals(ticket.subject_redacted, ticket.body_redacted)
    base = {"ticket_id": ticket.id, "prompt_version": prompt.PROMPT_VERSION}
    if provider is None:
        row = Classification(
            **base,
            status="unavailable",
            provider="none",
            requires_human=True,
            is_injection=bool(heuristics) or None,
            error="no model provider configured",
        )
        session.add(row)
        return row

    user = prompt.user_message(ticket.channel, ticket.customer_category, ticket.subject_redacted, ticket.body_redacted)
    last_error = "unknown"
    for _attempt in range(2):
        started = time.perf_counter()
        try:
            result = await provider.structured(
                system=prompt.SYSTEM,
                user=user,
                tool_name=prompt.TOOL_NAME,
                tool_description=prompt.TOOL_DESCRIPTION,
                schema=prompt.SCHEMA,
                max_tokens=400,
            )
        except PiiLeakBlocked:
            row = Classification(
                **base, status="failed", provider=provider.name, requires_human=True, error="pii_blocked"
            )
            session.add(row)
            return row
        except (ProviderUnavailable, ValueError) as exc:
            session.add(
                ModelUsage(
                    provider=provider.name, model="unknown", operation="classify", ticket_id=ticket.id,
                    latency_ms=int((time.perf_counter() - started) * 1000), success=False,
                )
            )  # fmt: skip
            last_error = type(exc).__name__
            continue
        session.add(
            ModelUsage(
                provider=provider.name,
                model=result.model,
                operation="classify",
                ticket_id=ticket.id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                estimated_cost_usd=_cost(settings, result.input_tokens, result.output_tokens),
                success=True,
            )
        )
        try:
            out = ClassificationOutput.model_validate(result.data)
        except ValidationError:
            last_error = "schema_validation_failed"
            continue
        requires_human = (
            out.requires_human or out.confidence < settings.classification_confidence_threshold or bool(heuristics)
        )
        row = Classification(
            **base,
            status="ok",
            provider=provider.name,
            model=result.model,
            category=out.category,
            subcategory=out.subcategory,
            intent=out.intent,
            priority=out.priority,
            language=out.language,
            is_injection=out.is_injection or bool(heuristics),
            confidence=out.confidence,
            requires_human=requires_human,
            explanation=out.explanation,
        )
        session.add(row)
        return row
    row = Classification(
        **base,
        status="invalid" if last_error == "schema_validation_failed" else "failed",
        provider=provider.name,
        requires_human=True,
        is_injection=bool(heuristics) or None,
        error=last_error,
    )
    session.add(row)
    return row
