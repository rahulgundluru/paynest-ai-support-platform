"""Dashboard analytics. Every number is computed from stored data at request time, region-scoped.

Where a metric cannot be measured yet (e.g. AI classification without a model), it is returned as
`null`/0 with an explicit note, never estimated.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select, text

from app.api.deps import Principal, SessionDep, require
from app.api.scoping import region_filter
from app.core.rbac import Permission
from app.models.approvals import Approval
from app.models.processing import Classification, Incident, IncidentLink, RoutingDecision
from app.models.tickets import SlaTracking, Ticket

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
Reader = Annotated[Principal, Depends(require(Permission.TICKETS_READ))]
# IST has no daylight saving, so a fixed +05:30 offset is exact (and works without a tz database).
_IST_WALL = func.timezone("UTC", Ticket.created_at) + text("interval '5 hours 30 minutes'")
IST_DAY = func.to_char(_IST_WALL, "YYYY-MM-DD")
IST_MONTH = func.to_char(_IST_WALL, "YYYY-MM")
CLOSED = ("closed", "resolved")


def _pairs(rows: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in rows}


def _f(value: Any) -> float | None:
    return None if value is None else round(float(value), 4)


@router.get("/summary")
async def summary(session: SessionDep, principal: Reader) -> dict[str, Any]:
    scope = region_filter(principal, Ticket.region)
    t = (
        await session.execute(
            select(
                func.count(Ticket.id),
                func.count().filter(Ticket.status.in_(CLOSED)),
                func.count().filter(Ticket.ingestion_status == "requires_review"),
                func.count().filter(Ticket.in_payroll_window),
                func.avg(func.extract("epoch", Ticket.first_response_at - Ticket.created_at) / 3600),
                func.percentile_cont(0.5).within_group(
                    func.extract("epoch", Ticket.first_response_at - Ticket.created_at) / 3600
                ),
                func.count().filter(Ticket.first_queue.is_not(None)),
                func.count().filter(Ticket.first_queue.is_not(None), Ticket.first_queue == Ticket.final_queue),
            ).where(scope)
        )
    ).one()
    total, closed, needs_review, in_window, avg_fr, median_fr, routed, first_touch = t
    sla = (
        await session.execute(
            select(
                func.count().filter(SlaTracking.applicable),
                func.count().filter(SlaTracking.resolution_breached.is_(True)),
                func.coalesce(func.sum(SlaTracking.credit_usd), 0),
                func.count().filter(SlaTracking.first_response_breached.is_(True)),
            )
            .join(Ticket, Ticket.id == SlaTracking.ticket_id)
            .where(scope)
        )
    ).one()
    cases = _pairs(
        (
            await session.execute(
                select(Incident.kind, func.count(Incident.id))
                .where(region_filter(principal, Incident.region), Incident.status == "open")
                .group_by(Incident.kind)
            )
        ).all()
    )
    duplicate_tickets = await session.scalar(
        select(func.count(distinct(IncidentLink.ticket_id)))
        .join(Incident, Incident.id == IncidentLink.incident_id)
        .where(region_filter(principal, Incident.region), IncidentLink.role == "resubmit", IncidentLink.active)
    )
    classified = await session.scalar(
        select(func.count(distinct(Classification.ticket_id)))
        .join(Ticket, Ticket.id == Classification.ticket_id)
        .where(scope, Classification.status == "ok")
    )
    latest = (
        select(RoutingDecision.ticket_id, func.max(RoutingDecision.id).label("id")).group_by(RoutingDecision.ticket_id)
    ).subquery()
    lanes = _pairs(
        (
            await session.execute(
                select(RoutingDecision.lane, func.count())
                .join(latest, latest.c.id == RoutingDecision.id)
                .join(Ticket, Ticket.id == RoutingDecision.ticket_id)
                .where(scope)
                .group_by(RoutingDecision.lane)
            )
        ).all()
    )
    approvals = _pairs(
        (
            await session.execute(
                select(Approval.status, func.count())
                .where(region_filter(principal, Approval.region))
                .group_by(Approval.status)
            )
        ).all()
    )
    routed_total = sum(lanes.values())
    return {
        "tickets": {
            "total": total,
            "closed_or_resolved": closed,
            "open": total - closed,
            "ingestion_requires_review": needs_review,
            "payroll_window_share": _f(in_window / total) if total else None,
        },
        "first_response_hours": {"mean": _f(avg_fr), "median": _f(median_fr)},
        "sla": {
            "applicable": sla[0],
            "resolution_breaches": sla[1],
            "credits_usd": str(Decimal(sla[2]).quantize(Decimal("0.01"))),
            "first_response_breaches": sla[3],
        },
        "duplicates": {
            "resubmission_cases": cases.get("resubmission", 0),
            "resubmitted_tickets": duplicate_tickets or 0,
            "incidents": cases.get("incident", 0),
        },
        "ai": {
            "classified_tickets": classified or 0,
            "note": None if classified else "No AI model configured yet: no ticket has an AI classification.",
            "routing_decisions": routed_total,
            "lanes": lanes,
            "automation_rate": _f(lanes.get("auto_answer", 0) / routed_total) if routed_total else None,
            "automation_note": "Auto-answer is disabled in the pilot until shadow-mode evidence exists.",
        },
        "human_review": {
            "pending": approvals.get("pending", 0),
            "by_status": approvals,
        },
        "routing_baseline": {
            "first_touch_correct": first_touch,
            "routed": routed,
            "rate": _f(first_touch / routed) if routed else None,
            "note": "Today's practice: the customer's own category pick vs the final queue (G2 must beat this).",
        },
    }


@router.get("/ticket-trends")
async def ticket_trends(session: SessionDep, principal: Reader) -> dict[str, Any]:
    scope = region_filter(principal, Ticket.region)
    days = (
        await session.execute(
            select(
                IST_DAY.label("day"),
                func.count(),
                func.count().filter(Ticket.in_payroll_window),
            )
            .where(scope)
            .group_by("day")
            .order_by("day")
        )
    ).all()
    resubmits = _pairs(
        (
            await session.execute(
                select(IST_DAY.label("day"), func.count(distinct(Ticket.id)))
                .join(IncidentLink, IncidentLink.ticket_id == Ticket.id)
                .where(scope, IncidentLink.role.in_(["resubmit", "member"]), IncidentLink.active)
                .group_by("day")
            )
        ).all()
    )
    return {
        "timezone": "IST (UTC+05:30)",
        "days": [
            {"day": d, "tickets": n, "payroll_window": w > 0, "grouped_into_cases": resubmits.get(d, 0)}
            for d, n, w in days
        ],
    }


async def _counts(session: SessionDep, principal: Principal, column: Any) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(func.coalesce(column, "unknown").label("key"), func.count())
            .where(region_filter(principal, Ticket.region))
            .group_by("key")
            .order_by(func.count().desc())
        )
    ).all()
    return [{"key": k, "count": n} for k, n in rows]


@router.get("/breakdowns")
async def breakdowns(session: SessionDep, principal: Reader) -> dict[str, Any]:
    return {
        "channel": await _counts(session, principal, Ticket.channel),
        "region": await _counts(session, principal, Ticket.region),
        "customer_category": await _counts(session, principal, Ticket.customer_category),
        "final_queue": await _counts(session, principal, Ticket.final_queue),
        "priority": await _counts(session, principal, Ticket.priority),
    }


@router.get("/sla-performance")
async def sla_performance(session: SessionDep, principal: Reader) -> dict[str, Any]:
    scope = region_filter(principal, Ticket.region)
    by_contract = (
        await session.execute(
            select(
                SlaTracking.tier,
                SlaTracking.priority,
                func.count(),
                func.count().filter(SlaTracking.resolution_breached.is_(True)),
                func.coalesce(func.sum(SlaTracking.credit_usd), 0),
            )
            .join(Ticket, Ticket.id == SlaTracking.ticket_id)
            .where(scope, SlaTracking.applicable)
            .group_by(SlaTracking.tier, SlaTracking.priority)
            .order_by(SlaTracking.tier, SlaTracking.priority)
        )
    ).all()
    by_month = (
        await session.execute(
            select(
                IST_MONTH.label("month"),
                func.count().filter(SlaTracking.resolution_breached.is_(True)),
                func.coalesce(func.sum(SlaTracking.credit_usd), 0),
                func.count().filter(SlaTracking.applicable),
            )
            .join(Ticket, Ticket.id == SlaTracking.ticket_id)
            .where(scope)
            .group_by("month")
            .order_by("month")
        )
    ).all()
    misrouted = (
        await session.execute(
            select(
                func.count().filter(SlaTracking.credit_usd.is_not(None)),
                func.coalesce(func.sum(SlaTracking.credit_usd).filter(Ticket.reassignment_count > 0), 0),
                func.coalesce(func.sum(SlaTracking.credit_usd), 0),
            )
            .join(Ticket, Ticket.id == SlaTracking.ticket_id)
            .where(scope)
        )
    ).one()
    total_credit = Decimal(misrouted[2])
    return {
        "attribution_note": "Credits are attributed to the month the ticket was created (Finance's cost sheet basis).",
        "by_contract": [
            {"tier": t, "priority": p, "tickets": n, "breaches": b, "credits_usd": str(c)}
            for t, p, n, b, c in by_contract
        ],
        "by_month": [
            {
                "month": m,
                "breaches": b,
                "credits_usd": str(c),
                "breach_rate": _f(b / n) if n else None,
            }
            for m, b, c, n in by_month
        ],
        "credits_from_tickets_that_changed_queue": {
            "credits_usd": str(Decimal(misrouted[1])),
            "share": _f(Decimal(misrouted[1]) / total_credit) if total_credit else None,
        },
    }


@router.get("/routing-performance")
async def routing_performance(session: SessionDep, principal: Reader) -> dict[str, Any]:
    """Today's routing baseline per first queue: share of tickets that stayed in the queue they started in."""
    rows = (
        await session.execute(
            select(
                Ticket.first_queue,
                func.count(),
                func.count().filter(Ticket.first_queue == Ticket.final_queue),
                func.count().filter(Ticket.in_payroll_window),
                func.count().filter(Ticket.in_payroll_window, Ticket.first_queue == Ticket.final_queue),
            )
            .where(region_filter(principal, Ticket.region), Ticket.first_queue.is_not(None))
            .group_by(Ticket.first_queue)
            .order_by(func.count().desc())
        )
    ).all()
    return {
        "basis": "customer_pick",
        "queues": [
            {
                "queue": q,
                "tickets": n,
                "stayed": s,
                "rate": _f(s / n) if n else None,
                "payroll_window_rate": _f(ws / w) if w else None,
            }
            for q, n, s, w, ws in rows
        ],
    }
