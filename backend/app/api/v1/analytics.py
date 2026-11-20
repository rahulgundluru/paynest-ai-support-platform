"""Cost analytics. Every input is labelled by provenance:
  measured        - computed from Finance's cost sheet, the SLA engine or recorded model usage
  source_estimate - a figure stated in the case sources (Session 4 cost tables, Oct 2026 list prices)
  assumption      - a planning assumption, editable through query parameters
Cash savings are only avoided SLA credits. Agent time released by drafts is reported as capacity,
not as a saving: it becomes a saving only if staffing decisions change (CFO 02: headcount is an output).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text

from app.api.deps import Principal, SessionDep, require
from app.core.rbac import Permission
from app.models.evaluation import MonthlyCost
from app.models.processing import ModelUsage

router = APIRouter(prefix="/analytics", tags=["analytics"])
Reader = Annotated[Principal, Depends(require(Permission.SLA_READ))]
BUDGET_CAP_USD = Decimal("4500")  # CFO email thread, 5 Oct 2026
SCENARIOS = {
    # name: (credit reduction of addressable credits, drafts per month, infra USD/month, cost per draft USD)
    "best": (Decimal("0.75"), 4000, Decimal("420"), Decimal("0.0155")),
    "expected": (Decimal("0.50"), 6000, Decimal("420"), Decimal("0.0155")),
    "conservative": (Decimal("0.25"), 15000, Decimal("1120"), Decimal("0.02")),
}
EMBEDDINGS_USD = Decimal("0.90")  # Session 4: ~9M tokens x USD 0.10/M


def q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@router.get("/model-usage")
async def model_usage(session: SessionDep, _: Reader) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                ModelUsage.provider,
                ModelUsage.model,
                ModelUsage.operation,
                func.count(),
                func.coalesce(func.sum(ModelUsage.input_tokens), 0),
                func.coalesce(func.sum(ModelUsage.output_tokens), 0),
                func.sum(ModelUsage.estimated_cost_usd),
                func.percentile_cont(0.95).within_group(ModelUsage.latency_ms),
            ).group_by(ModelUsage.provider, ModelUsage.model, ModelUsage.operation)
        )
    ).all()
    return {
        "calls": [
            {
                "provider": p,
                "model": m,
                "operation": o,
                "calls": n,
                "input_tokens": int(i),
                "output_tokens": int(out),
                "cost_usd": str(c) if c is not None else None,
                "latency_ms_p95": float(lat) if lat is not None else None,
            }
            for p, m, o, n, i, out, c, lat in rows
        ],
        "note": None if rows else "No model calls recorded: no model is configured yet.",
    }


@router.get("/cost")
async def cost(
    session: SessionDep,
    _: Reader,
    implementation_cost_usd: Annotated[Decimal | None, Query(ge=0)] = None,
    minutes_saved_per_draft: Annotated[Decimal, Query(ge=0, le=60)] = Decimal("4"),
    fte_hours_per_month: Annotated[Decimal, Query(gt=0, le=250)] = Decimal("160"),
) -> dict[str, Any]:
    months = list(
        await session.scalars(select(MonthlyCost).where(MonthlyCost.month >= "2026-07").order_by(MonthlyCost.month))
    )
    if not months:
        return {"error": "Cost sheet not loaded; run ingestion first."}
    n = Decimal(len(months))
    support = sum((m.agent_loaded_cost_usd + m.tooling_usd for m in months), Decimal(0)) / n
    tickets = Decimal(sum(m.tickets_received_all_customers for m in months)) / n
    credits = sum((m.sla_credits_paid_usd for m in months), Decimal(0)) / n
    # Credits on tickets that changed queue or were answered from an article no longer in force (Q3 extract)
    addressable_q3 = Decimal(
        await session.scalar(
            text(
                "SELECT coalesce(sum(s.credit_usd), 0) FROM sla_tracking s JOIN tickets t ON t.id = s.ticket_id "
                "WHERE s.credit_usd IS NOT NULL AND (t.reassignment_count > 0 OR EXISTS (SELECT 1 FROM ticket_events e "
                "WHERE e.ticket_id = t.id AND e.event_type = 'replied' AND ((e.data->>'kb_article_id' IN ('KB-0142','KB-0143') "
                "AND e.occurred_at >= '2026-08-01T00:00:00+05:30') OR (e.data->>'kb_article_id' IN ('KB-0201','KB-0202') "
                "AND e.occurred_at >= '2026-07-15T00:00:00+05:30'))))"
            )
        )
        or 0
    )
    total_q3 = Decimal(await session.scalar(text("SELECT coalesce(sum(credit_usd), 0) FROM sla_tracking")) or 0)
    addressable_share = (addressable_q3 / total_q3) if total_q3 else Decimal(0)
    measured_drafts = await session.scalar(
        select(func.count()).where(ModelUsage.operation == "draft", ModelUsage.success.is_(True))
    )
    measured_draft_cost = await session.scalar(
        select(func.avg(ModelUsage.estimated_cost_usd)).where(ModelUsage.operation == "draft")
    )

    scenarios = {}
    for name, (reduction, drafts, infra, per_draft_estimate) in SCENARIOS.items():
        per_draft = Decimal(measured_draft_cost) if measured_draft_cost else per_draft_estimate
        ai = Decimal(drafts) * per_draft + EMBEDDINGS_USD
        platform = infra + ai
        avoided = credits * addressable_share * reduction
        net = avoided - platform
        hours = Decimal(drafts) * minutes_saved_per_draft / 60
        payback = None
        if implementation_cost_usd is not None and net > 0:
            payback = q2(implementation_cost_usd / net)
        scenarios[name] = {
            "inputs": {
                "drafts_per_month": {"value": drafts, "provenance": "assumption"},
                "cost_per_draft_usd": {
                    "value": str(per_draft),
                    "provenance": "measured" if measured_draft_cost else "source_estimate",
                },
                "infrastructure_usd_month": {"value": str(infra), "provenance": "source_estimate"},
                "embeddings_usd_month": {"value": str(EMBEDDINGS_USD), "provenance": "source_estimate"},
                "share_of_addressable_credits_avoided": {"value": str(reduction), "provenance": "assumption"},
            },
            "ai_platform_cost_usd_month": str(q2(platform)),
            "within_budget_cap": platform <= BUDGET_CAP_USD,
            "budget_headroom_usd": str(q2(BUDGET_CAP_USD - platform)),
            "credits_avoided_usd_month": str(q2(avoided)),
            "net_cash_effect_usd_month": str(q2(net)),
            "cost_per_ticket_incl_credits_usd": str(q2((support + credits - avoided + platform) / tickets)),
            "released_capacity_hours_month": str(q2(hours)),
            "released_capacity_fte": str(q2(hours / fte_hours_per_month)),
            "payback_months": str(payback) if payback is not None else None,
            "payback_note": None
            if payback is not None
            else (
                "Provide implementation_cost_usd (not in the sources) to compute payback."
                if implementation_cost_usd is None
                else "No payback: the net monthly cash effect is not positive in this scenario."
            ),
        }
    return {
        "baseline": {
            "period": f"{months[0].month}..{months[-1].month}",
            "provenance": "measured (Finance cost sheet)",
            "support_cost_usd_month": str(q2(support)),
            "tickets_month": str(q2(tickets)),
            "sla_credits_usd_month": str(q2(credits)),
            "cost_per_ticket_excl_credits_usd": str(q2(support / tickets)),
            "cost_per_ticket_incl_credits_usd": str(q2((support + credits) / tickets)),
            "addressable_credit_share": str(q2(addressable_share * 100)) + "%",
            "addressable_credit_share_provenance": "measured (SLA engine on the Q3 extract: misrouted or stale-KB tickets)",
            "budget_cap_usd_month": str(BUDGET_CAP_USD),
        },
        "measured_ai": {
            "draft_calls": measured_drafts or 0,
            "note": None
            if measured_drafts
            else "No drafts generated yet (no model configured); per-draft cost uses the source estimate.",
        },
        "assumptions": {
            "minutes_saved_per_draft": {"value": str(minutes_saved_per_draft), "provenance": "assumption"},
            "fte_hours_per_month": {"value": str(fte_hours_per_month), "provenance": "assumption"},
            "implementation_cost_usd": {
                "value": str(implementation_cost_usd) if implementation_cost_usd is not None else None,
                "provenance": "assumption (user input)",
            },
        },
        "scenarios": scenarios,
        "notes": [
            "Cash savings count only avoided SLA credits. Released capacity is agent time, not a saving, unless staffing changes.",
            "Not every ticket is automated: drafts still go to an agent; auto-answer is locked in the pilot.",
            "Infrastructure figures are Session 4 list-price estimates (AWS two regions; the conservative case adds a managed "
            "search service). Verify with the AWS Pricing Calculator before committing.",
        ],
    }
