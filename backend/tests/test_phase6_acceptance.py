"""Phase 6 acceptance: gates execute against real data and report honestly; cost model separates
measured values, source estimates and assumptions."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import get_sessionmaker
from app.models.identity import Region, RoleName
from app.services.approvals.service import build_review_queue
from app.services.deduplication.service import run_detection
from app.services.ingestion.pipeline import run_ingestion
from app.services.knowledge.ingest import index_knowledge
from app.services.routing.service import route_all
from app.services.validation.output import DocValidity, RuleFacts, ValidationContext, validate_draft

SOURCE = Path(os.environ["DATA_SOURCE_DIR"])
pytestmark = [
    pytest.mark.ingested,
    pytest.mark.skipif(not (SOURCE / "data-room").is_dir(), reason="source data not fetched"),
]
BOTH = (Region.IN, Region.UAE)


@pytest.fixture(scope="module")
async def data():
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "TRUNCATE users, ingestion_batches, customers, agents, knowledge_documents, statutory_rules, "
                "system_configurations, evaluation_runs, monthly_costs CASCADE"
            )
        )
        await session.commit()
        await run_ingestion(session, SOURCE)
        await index_knowledge(session, SOURCE)
        await run_detection(session)
        await route_all(session)
        await build_review_queue(session)


async def _login(client, make_user, roles, regions=BOTH):
    email = f"u{uuid.uuid4().hex[:8]}@paynest.test"
    _, password = await make_user(email=email, roles=roles, regions=regions)
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    client.cookies.clear()
    return {"Authorization": f"Bearer {token['access_token']}"}


async def test_gates_execute_and_report_honestly(data, client, make_user):
    lead = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    agent = await _login(client, make_user, (RoleName.AGENT_L1,))
    assert (await client.post("/api/v1/evaluations/run", json={"gates": ["G1"]}, headers=agent)).status_code == 403
    assert (await client.post("/api/v1/evaluations/run", json={"gates": ["G9"]}, headers=lead)).status_code == 422
    runs = (
        await client.post("/api/v1/evaluations/run", json={"gates": ["G1", "G2", "G3", "G4", "G5", "G6"]}, headers=lead)
    ).json()
    by_gate = {r["gate"]: r for r in runs}
    assert by_gate["G1"]["status"] == "pass" and by_gate["G1"]["metrics"]["total_leaks"] == 0
    assert by_gate["G2"]["status"] == "not_run" and by_gate["G2"]["metrics"]["model_accuracy"] is None
    assert by_gate["G2"]["metrics"]["baseline_accuracy"] == pytest.approx(0.8485, abs=1e-4)
    assert by_gate["G3"]["status"] == "fail" and by_gate["G3"]["metrics"]["correct_links"] == 25  # honest 25/26
    assert by_gate["G3"]["metrics"]["meridian_incident_tickets"] == 30
    assert by_gate["G4"]["status"] == "pass" and by_gate["G4"]["metrics"]["false_positives_real_tickets"] == []
    assert by_gate["G5"]["status"] == "partial" and by_gate["G5"]["metrics"]["faithfulness"] is None
    assert by_gate["G5"]["metrics"]["stale_chunks_retrieved"] == 0
    assert by_gate["G6"]["status"] == "pass" and by_gate["G6"]["metrics"]["catch_rate"] == 1.0

    gates = (await client.get("/api/v1/evaluations/gates", headers=lead)).json()
    assert [g["gate"] for g in gates] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert gates[6]["latest"] is None  # G7 not run in this test: shown as never run, not as passed
    g3 = next(g for g in gates if g["gate"] == "G3")
    detail = (await client.get(f"/api/v1/evaluations/{g3['latest']['id']}", headers=lead)).json()
    assert detail["cases"][0]["passed"] is False  # failed cases listed first
    assert g3["failed_cases"] >= 1


async def test_evaluation_side_effects_are_rolled_back(data):
    async with get_sessionmaker()() as session:
        before = await session.scalar(text("SELECT count(*) FROM retrieval_logs WHERE ticket_id IS NULL"))
    from app.core.config import get_settings
    from app.services.evaluation.runner import run_gates

    await run_gates(["G5"], get_settings())
    async with get_sessionmaker()() as session:
        after = await session.scalar(text("SELECT count(*) FROM retrieval_logs WHERE ticket_id IS NULL"))
    assert after == before


async def test_cost_model_baseline_and_scenarios(data, client, make_user):
    finance = await _login(client, make_user, (RoleName.FINANCE_VIEWER,))
    cost = (await client.get("/api/v1/analytics/cost", headers=finance)).json()
    base = cost["baseline"]
    assert base["support_cost_usd_month"] == "90460.00"
    assert base["tickets_month"] == "15008.00"
    assert base["sla_credits_usd_month"] == "6398.65"
    assert base["addressable_credit_share"].startswith("59.9")
    for name in ("best", "expected", "conservative"):
        s = cost["scenarios"][name]
        assert s["within_budget_cap"] is True
        assert s["payback_months"] is None and "implementation_cost_usd" in s["payback_note"]
        assert s["inputs"]["share_of_addressable_credits_avoided"]["provenance"] == "assumption"
        assert s["inputs"]["cost_per_draft_usd"]["provenance"] == "source_estimate"
    with_cost = (await client.get("/api/v1/analytics/cost?implementation_cost_usd=20000", headers=finance)).json()
    expected = with_cost["scenarios"]["expected"]
    assert Decimal(expected["payback_months"]) > 0
    usage = (await client.get("/api/v1/analytics/model-usage", headers=finance)).json()
    assert usage["calls"] == [] and usage["note"]


def test_validator_allows_citing_an_outdated_article_only_to_explain_it():
    from datetime import date

    ctx = ValidationContext(
        ticket_date=date(2026, 9, 26), region="UAE", category="statutory", customer_name="X LLC",
        other_customer_names=[], ticket_tokens=set(),
        rules=[RuleFacts("R-UAE-WPS-2026-07", "UAE", date(2026, 7, 15), "SIF v2 (14 columns)", "SIF v3 (16 columns)")],
        documents={
            "R-UAE-WPS-2026-07": [DocValidity(date(2026, 7, 15), None)],
            "KB-0202": [DocValidity(None, date(2026, 7, 14))],
        },
        statutory_answer=True, superseded_by={"KB-0202": "R-UAE-WPS-2026-07"},
    )  # fmt: skip
    explained = (
        "Since 15 Jul 2026 the SIF is v3 with 16 columns (R-UAE-WPS-2026-07); KB-0202 describes the old v2 layout."
    )
    assert validate_draft(explained, ctx).passed
    relying = "Use KB-0202 together with R-UAE-WPS-2026-07 for the file."
    assert not validate_draft(relying, ctx).passed  # no "old/outdated" wording: still rejected
    alone = "KB-0202 is outdated."
    assert not validate_draft(alone, ctx).passed  # superseding rule not cited: still rejected
