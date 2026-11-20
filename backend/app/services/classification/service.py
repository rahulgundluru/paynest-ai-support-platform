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
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import classification as prompt
from app.ai.providers.base import LLMProvider, PiiLeakBlocked, ProviderUnavailable, StructuredResult
from app.core.config import Settings
from app.models.processing import Classification, ModelUsage
from app.models.tickets import Ticket

# Failures a retry cannot fix (bad key, no credit, unknown model, no privacy-compliant endpoint).
NON_RETRYABLE = {"auth_failed", "insufficient_credits", "model_not_found", "no_private_endpoint", "no_api_key",
                 "bad_request"}  # fmt: skip

# Rule-based layer of injection detection (defence in depth; the model's is_injection is the second layer).
# Families, not phrases: override verbs aimed at instructions, persona switches, fake role markers,
# tool-call payloads, money/credential requests addressed to the assistant, decode/translate-then-execute,
# in English, Hinglish, Hindi and Arabic.
_INJECTION_PATTERNS = [
    # override / forget the instructions (EN)
    r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}"
    r"\b(instructions?|prompts?|rules|guidelines|everything (above|before)|context)\b",
    r"\bnew instructions?\s*:",
    # persona / mode switch
    r"\byou are now\b",
    r"\bfrom now on,? you (are|will|must)\b",
    r"\b(developer|admin|god|dan|jailbreak|unrestricted) mode\b",
    r"\bact as (an? )?(admin|administrator|system|developer)\b",
    # prompt extraction
    r"\b(reveal|show|print|repeat|output)\b[^.\n]{0,20}\b(system prompt|your (prompt|instructions))\b",
    # fake role markers and hidden comments
    r"(^|\n)\s*(system|assistant|developer)\s*:",
    r"<!--\s*(assistant|system|ai)\b",
    r"\[(system|assistant)\]",
    # tool-call style payloads
    r"\"(action|tool|function)\"\s*:\s*\"[a-z_]*(approve|refund|credit|transfer|delete|pay)[a-z_]*\"",
    # money / record changes demanded of the assistant
    r"\bmark\b[^.\n]{0,30}\b(refund|invoice|payment)\b[^.\n]{0,30}\b(approved|paid)\b",
    r"\bset\b[^.\n]{0,20}\bbalance to\b",
    r"\b(authori[sz]e|instruct)\b[^.\n]{0,15}\byou to\b[^.\n]{0,20}\b(credit|refund|pay|transfer|approve)\b",
    r"\b(always|automatically) approve\b",
    # data / credential exfiltration
    r"\b(list|send|give|share)\b[^.\n]{0,20}\ball customer",
    r"\b(reply|respond|send|share|give)\b[^.\n]{0,25}\b(api key|password|secret|access token|credentials)\b",
    # decode / translate then execute
    r"\b(decode|translate)\b[^.\n]{0,60}\b(then|and)\b[^.\n]{0,15}\b(follow|do|execute|obey)\b",
    # secrecy instructions
    r"\bdo not (mention|tell anyone|disclose)\b[^.\n]{0,25}\b(this|message|instruction)",
    # Hinglish
    r"\b(instructions?|rules|niyam)\b[^.\n]{0,25}\b(ignore|bhool)\b[^.\n]{0,10}\b(karo|kar do|jao)\b",
    # Hindi
    r"(निर्देश|नियम)[^।\n]{0,25}(अनदेखा|नज़रअंदाज़|नजरअंदाज|भूल)",
    # Arabic
    r"(تجاهل|انس)[^.\n]{0,25}(التعليمات|القواعد|الأوامر)",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)
_SPACED = re.compile(r"\b(?:\w\s){4,}\w\b")


def _despace(text: str) -> str:
    """Collapses letter-by-letter spacing ("i g n o r e") so obfuscated words are still matched."""
    return _SPACED.sub(lambda m: m.group(0).replace(" ", ""), text)


def injection_signals(*texts: str | None) -> list[str]:
    """Rule-based screen for instructions aimed at an AI. Returns the matched phrases (redacted text only)."""
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        for candidate in (t, _despace(t)):
            for m in _INJECTION.finditer(candidate):
                phrase = m.group(0).strip()
                if phrase not in found:
                    found.append(phrase)
    return found


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


def usage_cost(settings: Settings, result: StructuredResult) -> tuple[Decimal | None, str | None]:
    """Provider-reported cost when available, otherwise the configured price table, otherwise unknown."""
    if result.cost_usd is not None:
        return result.cost_usd, "provider_reported"
    estimated = _cost(settings, result.input_tokens, result.output_tokens)
    return estimated, ("price_table" if estimated is not None else None)


async def classify_ticket(
    session: AsyncSession,
    ticket: Ticket,
    provider: LLMProvider | None,
    settings: Settings,
    threshold: float | None = None,
    *,
    run_id: uuid.UUID | None = None,
    unavailable_reason: str = "no model provider configured",
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
            error=unavailable_reason[:200],
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
            code = exc.code if isinstance(exc, ProviderUnavailable) else "invalid_output"
            session.add(
                ModelUsage(
                    provider=provider.name, model=getattr(provider, "model", None) or "unknown", operation="classify",
                    ticket_id=ticket.id, pipeline_run_id=run_id, prompt_version=prompt.PROMPT_VERSION,
                    latency_ms=int((time.perf_counter() - started) * 1000), success=False, error=code[:40],
                )
            )  # fmt: skip
            last_error = code if isinstance(exc, ProviderUnavailable) else type(exc).__name__
            if isinstance(exc, ProviderUnavailable) and code in NON_RETRYABLE:
                break
            continue
        cost, cost_source = usage_cost(settings, result)
        try:
            out = ClassificationOutput.model_validate(result.data)
        except ValidationError:
            out = None
        session.add(
            ModelUsage(
                provider=provider.name,
                model=result.model,
                operation="classify",
                ticket_id=ticket.id,
                pipeline_run_id=run_id,
                prompt_version=prompt.PROMPT_VERSION,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                estimated_cost_usd=cost,
                cost_source=cost_source,
                success=out is not None,
                error=None if out is not None else "schema_validation_failed",
                request_id=result.request_id,
                upstream_provider=result.upstream_provider,
            )
        )
        if out is None:
            last_error = "schema_validation_failed"
            continue
        requires_human = (
            out.requires_human
            or out.confidence < (threshold if threshold is not None else settings.classification_confidence_threshold)
            or bool(heuristics)
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
