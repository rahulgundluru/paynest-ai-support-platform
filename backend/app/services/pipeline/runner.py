"""Runs one ticket through the pipeline and records every step (timing, decision, cost) in `pipeline_runs`.

Order after intake: duplicates -> injection screen -> AI classification -> routing rules -> date-aware
retrieval -> AI draft -> output validation -> human review.

Rules that keep this safe:
- The model never routes, never approves and never decides whether it may draft: routing rules do.
- A ticket flagged by the injection screen gets no model call at all (R1 blocks it regardless).
- Before every model call the budget guard checks the daily and per-ticket caps.
- Any AI step that cannot run (switched off, no key, no model, cap reached, provider error) is recorded
  as such and the ticket goes to a person. Nothing is invented to fill the gap.
- Each step is committed as it finishes, so the flow view shows progress while the run is going.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.providers.base import LLMProvider
from app.core.config import Settings
from app.models.approvals import ApprovalEvent
from app.models.processing import Classification, ModelUsage, PipelineRun
from app.models.reference import Customer
from app.models.tickets import NormalizationLog, PiiDetection, SlaTracking, SourceRecord, Ticket
from app.services import ai_config, audit
from app.services.approvals.service import open_review, ticket_date, validation_context
from app.services.classification.service import classify_ticket, injection_signals
from app.services.deduplication.service import detect_for_ticket, membership
from app.services.drafting.service import draft_reply
from app.services.knowledge.retrieval import retrieve, statutory_rates
from app.services.pipeline.steps import blank_steps, merge, now_utc, step_record
from app.services.routing.service import route_ticket
from app.services.runtime_config import load_runtime_config
from app.services.validation.output import validate_draft

log = logging.getLogger(__name__)

ProviderFactory = Callable[[Settings, str | None], LLMProvider | None]
DRAFT_LANES = {"draft_for_agent"}
_AI_OFF = {
    "disabled": "AI is switched off in AI management",
    "no_provider": "No AI provider configured for this deployment (LLM_PROVIDER)",
    "no_key": "No OpenRouter API key configured on the server",
    "no_model": "No model selected in AI management",
}


def _ai_unavailable(cfg: ai_config.AiConfig, model: str | None) -> str | None:
    if cfg.provider != "openrouter":
        return "no_provider"
    if not cfg.key_configured:
        return "no_key"
    if not cfg.enabled:
        return "disabled"
    if not model:
        return "no_model"
    return None


async def _cost_of(session: AsyncSession, run_id: uuid.UUID, operation: str) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0)).where(
            ModelUsage.pipeline_run_id == run_id, ModelUsage.operation == operation
        )
    )
    return Decimal(str(total or 0))


async def start_run(
    session: AsyncSession,
    ticket: Ticket,
    *,
    trigger: str,
    actor: uuid.UUID | None,
    settings: Settings,
    intake_steps: list[dict[str, Any]] | None = None,
) -> PipelineRun:
    cfg = await ai_config.load(session, settings)
    steps = blank_steps()
    for record in intake_steps or await _existing_intake(session, ticket):
        steps = merge(steps, record)
    run = PipelineRun(ticket_id=ticket.id, trigger=trigger, status="running", steps=steps, ai_enabled=cfg.ready,
                      started_by=actor)  # fmt: skip
    session.add(run)
    await session.flush()
    return run


async def _existing_intake(session: AsyncSession, ticket: Ticket) -> list[dict[str, Any]]:
    """Intake steps for a ticket that already exists: reported from what was stored when it was ingested."""
    t = now_utc()
    record = await session.get(SourceRecord, ticket.source_record_id)
    pii = list(await session.scalars(select(PiiDetection).where(PiiDetection.ticket_id == ticket.id)))
    norm = await session.scalar(select(func.count()).where(NormalizationLog.ticket_id == ticket.id)) or 0
    customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
    sla = await session.get(SlaTracking, ticket.id)
    entities: dict[str, int] = {}
    for d in pii:
        entities[d.entity_type] = entities.get(d.entity_type, 0) + 1
    source = f"{record.source_file} #{record.record_index}" if record else "unknown source"
    return [
        step_record("received", "done", f"Stored earlier from {source}", {"source": source, "existing": True},
                    started=t, finished=t),
        step_record("pii", "done",
                    f"{len(pii)} personal value(s) tokenized at intake" if pii else "No personal identifiers found",
                    {"masked": len(pii), "entities": entities, "tokens": sorted({d.token for d in pii})},
                    started=t, finished=t),
        step_record("normalize", "review" if ticket.review_reasons else "done",
                    f"{norm} field mappings logged" + (f"; review: {', '.join(ticket.review_reasons)}"
                                                       if ticket.review_reasons else ""),
                    {"review_reasons": ticket.review_reasons}, started=t, finished=t),
        step_record("customer_sla", "done" if customer else "review",
                    f"{customer.name} · {customer.tier} · {customer.region}" if customer
                    else "Customer not verified",
                    {"customer_id": ticket.customer_id, "tier": customer.tier if customer else None,
                     "region": ticket.region,
                     "resolution_target_h": str(sla.resolution_target_h) if sla and sla.resolution_target_h else None,
                     "resolution_breached": sla.resolution_breached if sla else None,
                     "credit_usd": str(sla.credit_usd) if sla and sla.credit_usd is not None else None},
                    started=t, finished=t),
    ]  # fmt: skip


class _Run:
    def __init__(self, session: AsyncSession, run: PipelineRun) -> None:
        self.session = session
        self.run = run
        self.current: str | None = None

    async def begin(self, key: str) -> Any:
        self.current = key
        started = now_utc()
        self.run.steps = merge(self.run.steps, {"key": key, "status": "running", "started_at": started.isoformat()})
        await self.session.commit()
        return started

    async def finish(self, record: dict[str, Any]) -> None:
        self.run.steps = merge(self.run.steps, record)
        self.current = None
        await self.session.commit()


async def execute_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    settings: Settings,
    provider_factory: ProviderFactory | None = None,
) -> None:
    """Executes the post-intake steps of a run in its own session (called as a background task)."""
    factory = provider_factory or ai_config.build_provider
    async with sessionmaker() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        ticket = await session.get(Ticket, run.ticket_id)
        if ticket is None:
            return
        state = _Run(session, run)
        try:
            await _steps(session, state, ticket, settings, factory)
            run.total_cost_usd = await session.scalar(
                select(func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0)).where(
                    ModelUsage.pipeline_run_id == run.id
                )
            ) or Decimal("0")
            run.status, run.finished_at = "completed", now_utc()
            await audit.record(
                session, "pipeline.completed", actor_user_id=run.started_by, entity_type="ticket",
                entity_id=ticket.external_id or str(ticket.id), region=ticket.region,
                details={"run": str(run.id), "trigger": run.trigger, "cost_usd": str(run.total_cost_usd)},
            )  # fmt: skip
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - a failed run must be recorded, never left "running"
            log.exception("pipeline run failed", extra={"component": "pipeline", "error_type": type(exc).__name__})
            await session.rollback()
            run = await session.get(PipelineRun, run_id)
            if run is None:
                return
            if state.current:
                run.steps = merge(run.steps, {"key": state.current, "status": "failed",
                                              "summary": f"Step failed ({type(exc).__name__})"})  # fmt: skip
            run.steps = [
                {**s, "status": "skipped", "summary": "Not run: an earlier step failed"}
                if s["status"] == "pending"
                else s
                for s in run.steps
            ]
            run.status, run.finished_at, run.error = "failed", now_utc(), type(exc).__name__[:200]
            await session.commit()


async def _steps(
    session: AsyncSession, state: _Run, ticket: Ticket, settings: Settings, factory: ProviderFactory
) -> None:
    run = state.run
    routing_config, dedupe_config = await load_runtime_config(session)
    cfg = await ai_config.load(session, settings)

    # ---------------------------------------------------------------- duplicates & incidents
    started = await state.begin("duplicates")
    if run.trigger == "create":
        found = await detect_for_ticket(session, ticket, dedupe_config)
    else:
        found = await membership(session, ticket)
    outcome = found["outcome"]
    if outcome == "resubmission":
        summary = f"Follow-up of {found.get('parent')} ({found['rule_id']}): grouped into one case"
    elif outcome == "incident":
        summary = (f"Part of an incident ({found['rule_id']}): {found.get('tickets', 'several')} tickets, "
                   f"owned by {found['owner_queue']}")  # fmt: skip
    elif outcome == "skipped":
        summary = "Customer unknown: tickets are never linked across possibly different customers"
    elif outcome == "already_linked":
        summary = "Already part of a case"
    else:
        summary = "No follow-up signal and no incident burst for this customer"
    await state.finish(step_record("duplicates", "done" if outcome != "skipped" else "skipped", summary, found,
                                   started=started))  # fmt: skip

    # ---------------------------------------------------------------- injection screen
    started = await state.begin("injection")
    signals = injection_signals(ticket.subject_redacted, ticket.body_redacted)
    await state.finish(
        step_record(
            "injection", "blocked" if signals else "done",
            f"{len(signals)} instruction-like phrase(s) found: no model will see this ticket" if signals
            else "No instructions aimed at an AI found",
            {"signals": [s[:80] for s in signals]}, started=started,
        )
    )  # fmt: skip

    # ---------------------------------------------------------------- AI classification
    started = await state.begin("classify")
    reason = _ai_unavailable(cfg, cfg.classifier_model)
    budget = None if reason or signals else await ai_config.budget_block(session, cfg, ticket.id, now_utc())
    if signals:
        classification = await classify_ticket(session, ticket, None, settings, routing_config.confidence_threshold,
                                               run_id=run.id, unavailable_reason="injection screen")  # fmt: skip
        record = step_record("classify", "skipped", "Not sent to the model: the injection screen flagged the ticket",
                             {"reason": "injection_screen"}, started=started)  # fmt: skip
    elif reason or budget:
        why = _AI_OFF.get(reason or "", None) or (
            "Daily AI budget reached" if budget == "daily_budget_reached" else "This ticket's AI budget is used up"
        )
        classification = await classify_ticket(session, ticket, None, settings, routing_config.confidence_threshold,
                                               run_id=run.id, unavailable_reason=why)  # fmt: skip
        record = step_record("classify", "skipped", f"{why}; the customer's own category is used",
                             {"reason": reason or budget}, started=started)  # fmt: skip
    else:
        provider = factory(settings, cfg.classifier_model)
        classification = await classify_ticket(
            session, ticket, provider, settings, routing_config.confidence_threshold, run_id=run.id,
            unavailable_reason=_AI_OFF["no_key"],
        )  # fmt: skip
        await session.flush()
        cost = await _cost_of(session, run.id, "classify")
        record = _classification_record(classification, cost, started)
    await session.flush()
    await state.finish(record)

    # ---------------------------------------------------------------- routing
    started = await state.begin("routing")
    decision = await route_ticket(session, ticket, routing_config)
    await session.flush()
    await state.finish(
        step_record(
            "routing", "blocked" if decision.lane == "block" else "done",
            f"{decision.rule_id} → {decision.queue} ({decision.support_level}) · lane {decision.lane.replace('_', ' ')}"
            + (" · approval required" if decision.requires_approval else ""),
            {"rule_id": decision.rule_id, "rule_version": decision.rule_version, "lane": decision.lane,
             "queue": decision.queue, "support_level": decision.support_level,
             "requires_approval": decision.requires_approval, "reason": decision.reason,
             "inputs": {k: decision.inputs.get(k) for k in ("category", "category_source", "priority", "tier",
                                                            "classifier_confidence", "is_injection")}},
            started=started,
        )
    )  # fmt: skip

    # ---------------------------------------------------------------- retrieval
    started = await state.begin("retrieval")
    day = ticket_date(ticket)
    sources: list[dict[str, Any]] = []
    rates: list[dict[str, Any]] = []
    if ticket.region and decision.lane != "block":
        query = f"{ticket.subject_redacted or ''} {ticket.body_redacted or ''}"
        retrieval_id, hits = await retrieve(session, query, region=ticket.region, as_of=day, limit=4,
                                            ticket_id=ticket.id)  # fmt: skip
        sources = [
            {"document_id": h.document_id, "version": h.version, "title": h.title, "text": h.text[:1200],
             "content_complete": h.content_complete,
             "effective_from": h.effective_from.isoformat() if h.effective_from else None,
             "effective_to": h.effective_to.isoformat() if h.effective_to else None}
            for h in hits
        ]  # fmt: skip
        rates = [{"rule_id": r.rule_id, "title": r.title, "value": r.value}
                 for r in await statutory_rates(session, ticket.region, day)]  # fmt: skip
        await state.finish(
            step_record(
                "retrieval", "done",
                f"{len(sources)} source(s) and {len(rates)} statutory rate(s) in force on {day.strftime('%d %b %Y')}",
                {"as_of": day.isoformat(), "region": ticket.region, "retrieval_id": str(retrieval_id),
                 "sources": [{k: s[k] for k in ("document_id", "version", "title", "effective_from", "effective_to",
                                                "content_complete")} for s in sources],
                 "rates": rates},
                started=started,
            )
        )  # fmt: skip
    else:
        why = (
            "Blocked ticket: nothing is retrieved for an automated answer"
            if decision.lane == "block"
            else ("Region unknown: region-specific knowledge cannot be chosen")
        )
        await state.finish(step_record("retrieval", "skipped", why, {}, started=started))

    # ---------------------------------------------------------------- AI draft
    started = await state.begin("draft")
    draft_text: str | None = None
    draft_meta: dict[str, Any] = {}
    reason = _ai_unavailable(cfg, cfg.drafting_model)
    if decision.lane not in DRAFT_LANES:
        why = {
            "block": "Blocked by R1: no AI text is generated for this ticket",
            "human_review": f"{decision.rule_id}: a person handles this ticket first",
            "route_queue": f"Lane 'route queue': the {decision.queue} agent replies; no draft needed",
            "incident": "Part of an incident: the incident owner sends one update to the customer",
        }.get(decision.lane, f"Lane {decision.lane}: no draft")
        await state.finish(step_record("draft", "skipped", why, {"lane": decision.lane}, started=started))
    elif reason:
        await state.finish(step_record("draft", "skipped", f"{_AI_OFF[reason]}; the agent writes the reply",
                                       {"reason": reason}, started=started))  # fmt: skip
    elif budget := await ai_config.budget_block(session, cfg, ticket.id, now_utc()):
        why = "Daily AI budget reached" if budget == "daily_budget_reached" else "This ticket's AI budget is used up"
        await state.finish(step_record("draft", "skipped", f"{why}; the agent writes the reply", {"reason": budget},
                                       started=started))  # fmt: skip
    else:
        provider = factory(settings, cfg.drafting_model)
        customer = await session.get(Customer, ticket.customer_id) if ticket.customer_id else None
        if provider is None:
            await state.finish(step_record("draft", "skipped", _AI_OFF["no_key"], {}, started=started))
        else:
            result = await draft_reply(
                session, ticket, provider, settings, ticket_date=day.isoformat(),
                tier=customer.tier if customer else None,
                category=classification.category if classification.status == "ok" else ticket.customer_category,
                queue=decision.queue, sources=sources, rates=rates, run_id=run.id,
            )  # fmt: skip
            await session.flush()
            cost = await _cost_of(session, run.id, "draft")
            draft_meta = {"model": result.model, "citations": result.citations, "attempts": result.attempts,
                          "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                          "latency_ms": result.latency_ms, "insufficient_evidence": result.insufficient_evidence,
                          "error": result.error}  # fmt: skip
            if result.status == "ok" and result.reply:
                draft_text = result.reply
                words = len(result.reply.split())
                summary = (f"Draft written ({words} words)" + (f", cites {', '.join(result.citations)}"
                                                               if result.citations else ", no citations")
                           + f" · {result.latency_ms / 1000:.1f} s")  # fmt: skip
                if result.insufficient_evidence:
                    summary += " · sources did not fully answer: a specialist must confirm"
                status = "review" if result.insufficient_evidence else "done"
            else:
                status = "failed"
                summary = f"No usable draft ({result.error or result.status}); the agent writes the reply"
            await state.finish(step_record("draft", status, summary, draft_meta, started=started, cost_usd=cost))

    # ---------------------------------------------------------------- validation
    started = await state.begin("validation")
    report = None
    if draft_text:
        report = validate_draft(
            draft_text, await validation_context(session, ticket, statutory=decision.rule_id == "R7")
        )
        failed = [c.name for c in report.checks if not c.passed]
        await state.finish(
            step_record(
                "validation", "done" if report.passed else "failed",
                f"All {len(report.checks)} checks passed" if report.passed
                else f"{len(failed)} check(s) failed: {', '.join(failed)}: cannot be approved until fixed",
                report.as_dict(), started=started,
            )
        )  # fmt: skip
    else:
        await state.finish(step_record("validation", "skipped", "No AI draft to validate; a person's draft is "
                                       "validated when it is saved", {}, started=started))  # fmt: skip

    # ---------------------------------------------------------------- human review
    started = await state.begin("review")
    approval = await open_review(session, ticket, decision, has_draft=draft_text is not None)
    await session.flush()
    if approval is None:
        await state.finish(step_record("review", "done", f"Routed to {decision.queue}; no approval step required "
                                       f"({decision.rule_id})", {"required": False, "queue": decision.queue},
                                       started=started))  # fmt: skip
        return
    await session.refresh(approval, attribute_names=["events"])  # async: load the relationship before appending
    if draft_text and approval.draft_source != "human":
        approval.draft_text, approval.draft_source = draft_text, "ai"
        approval.validation = report.as_dict() if report else None
        approval.evidence = {
            **approval.evidence,
            "suggested_response": draft_text,
            "suggested_response_note": f"AI draft ({draft_meta.get('model')}); "
            + ("passed validation" if report and report.passed else "failed validation") + "; a person must review it",
        }  # fmt: skip
        approval.events.append(
            ApprovalEvent(action="ai_drafted", from_status=approval.status, to_status=approval.status,
                          details={"model": draft_meta.get("model"), "validation_passed": bool(report and report.passed),  # noqa: E501
                                   "run": str(run.id)})
        )  # fmt: skip
    await session.flush()
    second = " (two-person rule if a person edits the draft)" if decision.rule_id in ("R6", "R7") else ""
    await state.finish(
        step_record(
            "review", "review",
            f"Waiting for a person in {approval.queue}{second}" if approval.status == "pending"
            else f"Review item is {approval.status}",
            {"approval_id": str(approval.id), "status": approval.status, "queue": approval.queue,
             "rule_id": approval.rule_id, "draft_source": approval.draft_source},
            started=started,
        )
    )  # fmt: skip


def _classification_record(c: Classification, cost: Decimal, started: Any) -> dict[str, Any]:
    details = {"status": c.status, "model": c.model, "category": c.category, "priority": c.priority,
               "language": c.language, "confidence": c.confidence, "requires_human": c.requires_human,
               "is_injection": c.is_injection, "intent": c.intent, "error": c.error}  # fmt: skip
    if c.status == "ok":
        summary = (f"{(c.category or '').replace('_', ' ')} · {c.priority} · confidence {c.confidence:.2f}"
                   + (" · a person should decide" if c.requires_human else ""))  # fmt: skip
        status = "review" if c.requires_human else "done"
    else:
        summary = f"Classification {c.status} ({c.error}); the customer's own category is used"
        status = "failed"
    return step_record("classify", status, summary, details, started=started, cost_usd=cost)


async def latest_runs(session: AsyncSession, ticket_id: uuid.UUID, limit: int = 5) -> list[PipelineRun]:
    return list(
        await session.scalars(
            select(PipelineRun)
            .where(PipelineRun.ticket_id == ticket_id)
            .order_by(PipelineRun.started_at.desc())
            .limit(limit)
        )
    )


async def has_active_run(session: AsyncSession, ticket_id: uuid.UUID) -> bool:
    """A run still marked running within the last 10 minutes (older ones were interrupted, e.g. a restart)."""
    return bool(
        await session.scalar(
            select(func.count()).where(
                PipelineRun.ticket_id == ticket_id,
                PipelineRun.status == "running",
                PipelineRun.started_at > now_utc() - timedelta(minutes=10),
            )
        )
    )
