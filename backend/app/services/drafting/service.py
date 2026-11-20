"""AI reply drafting from date-aware sources. The draft is always reviewed by a person.

- Input: redacted ticket text, the knowledge chunks and statutory rates in force on the ticket date.
- Output: typed (reply, citations, insufficient_evidence), validated with Pydantic; one retry on bad output.
- Every attempt is recorded in `model_usage` with the provider-reported cost.
- The returned text is then checked by the deterministic validator (G6) before it reaches the review queue.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import drafting as prompt
from app.ai.providers.base import LLMProvider, PiiLeakBlocked, ProviderUnavailable
from app.core.config import Settings
from app.models.processing import ModelUsage
from app.models.tickets import Ticket
from app.services.classification.service import NON_RETRYABLE, usage_cost


class DraftOutput(BaseModel):
    reply: str = Field(min_length=1, max_length=1500)
    citations: list[str] = Field(default_factory=list, max_length=6)
    insufficient_evidence: bool


@dataclass
class DraftResult:
    status: str  # ok | failed | invalid | blocked
    reply: str | None = None
    citations: list[str] = field(default_factory=list)
    insufficient_evidence: bool = False
    model: str | None = None
    error: str | None = None
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0


async def draft_reply(
    session: AsyncSession,
    ticket: Ticket,
    provider: LLMProvider,
    settings: Settings,
    *,
    ticket_date: str,
    tier: str | None,
    category: str | None,
    queue: str,
    sources: list[dict[str, Any]],
    rates: list[dict[str, Any]],
    run_id: uuid.UUID | None = None,
) -> DraftResult:
    user = prompt.user_message(
        ticket_date=ticket_date, region=ticket.region, tier=tier, category=category, queue=queue,
        subject=ticket.subject_redacted, body=ticket.body_redacted, sources=sources, rates=rates,
    )  # fmt: skip
    out = DraftResult(status="failed")
    for _attempt in range(2):
        out.attempts += 1
        started = time.perf_counter()
        try:
            result = await provider.structured(
                system=prompt.SYSTEM, user=user, tool_name=prompt.TOOL_NAME,
                tool_description=prompt.TOOL_DESCRIPTION, schema=prompt.SCHEMA, max_tokens=700,
            )  # fmt: skip
        except PiiLeakBlocked:
            out.status, out.error = "blocked", "pii_blocked"
            return out
        except (ProviderUnavailable, ValueError) as exc:
            code = exc.code if isinstance(exc, ProviderUnavailable) else "invalid_output"
            elapsed = int((time.perf_counter() - started) * 1000)
            session.add(
                ModelUsage(
                    provider=provider.name, model=getattr(provider, "model", None) or "unknown", operation="draft",
                    ticket_id=ticket.id, pipeline_run_id=run_id, prompt_version=prompt.PROMPT_VERSION,
                    latency_ms=elapsed, success=False, error=code[:40],
                )
            )  # fmt: skip
            out.latency_ms += elapsed
            out.error = code
            if isinstance(exc, ProviderUnavailable) and code in NON_RETRYABLE:
                break
            continue
        cost, cost_source = usage_cost(settings, result)
        try:
            parsed: DraftOutput | None = DraftOutput.model_validate(result.data)
        except ValidationError:
            parsed = None
        session.add(
            ModelUsage(
                provider=provider.name, model=result.model, operation="draft", ticket_id=ticket.id,
                pipeline_run_id=run_id, prompt_version=prompt.PROMPT_VERSION,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens, latency_ms=result.latency_ms,
                estimated_cost_usd=cost, cost_source=cost_source, success=parsed is not None,
                error=None if parsed is not None else "schema_validation_failed",
                request_id=result.request_id, upstream_provider=result.upstream_provider,
            )
        )  # fmt: skip
        out.model = result.model
        out.cost_usd += cost or Decimal("0")
        out.latency_ms += result.latency_ms
        out.input_tokens += result.input_tokens
        out.output_tokens += result.output_tokens
        if parsed is None:
            out.status, out.error = "invalid", "schema_validation_failed"
            continue
        out.status, out.error = "ok", None
        out.reply = parsed.reply.strip()
        out.citations = parsed.citations
        out.insufficient_evidence = parsed.insufficient_evidence
        return out
    return out
