"""Phase 5 acceptance: dashboard numbers are computed from the data (and match the verified discovery
figures), the processing monitor reflects stored state, and runtime settings are bounded, audited and used."""

from __future__ import annotations

import json
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
                "system_configurations CASCADE"
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


async def test_dashboard_summary_matches_verified_figures(data, client, make_user):
    headers = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    s = (await client.get("/api/v1/dashboard/summary", headers=headers)).json()
    assert s["tickets"]["total"] == 1526  # 1,353 export + 112 WhatsApp + 61 phone
    assert s["sla"]["resolution_breaches"] == 128 and s["sla"]["credits_usd"] == "19195.95"
    assert s["duplicates"] == {"resubmission_cases": 26, "resubmitted_tickets": 26, "incidents": 2}
    assert s["ai"]["classified_tickets"] == 0 and s["ai"]["note"]  # no model: nothing invented
    assert s["ai"]["automation_rate"] == 0
    assert s["human_review"]["pending"] == 288
    assert (s["routing_baseline"]["first_touch_correct"], s["routing_baseline"]["routed"]) == (1126, 1327)
    assert s["first_response_hours"]["median"] > 0


async def test_breakdowns_trends_and_sla_are_consistent(data, client, make_user):
    headers = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    b = (await client.get("/api/v1/dashboard/breakdowns", headers=headers)).json()
    assert sum(r["count"] for r in b["channel"]) == 1526
    assert {r["key"]: r["count"] for r in b["channel"]}["whatsapp"] == 112
    days = (await client.get("/api/v1/dashboard/ticket-trends", headers=headers)).json()["days"]
    assert sum(d["tickets"] for d in days) == 1526
    sla = (await client.get("/api/v1/dashboard/sla-performance", headers=headers)).json()
    assert sum(Decimal(m["credits_usd"]) for m in sla["by_month"]) == Decimal("19195.95")
    assert 0.44 < sla["credits_from_tickets_that_changed_queue"]["share"] < 0.46  # 45.3 % (discovery)
    routing = (await client.get("/api/v1/dashboard/routing-performance", headers=headers)).json()
    assert sum(q["tickets"] for q in routing["queues"]) == 1327


async def test_dashboard_is_region_scoped(data, client, make_user):
    india = await _login(client, make_user, (RoleName.SUPPORT_LEAD,), (Region.IN,))
    both = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    in_total = (await client.get("/api/v1/dashboard/summary", headers=india)).json()["tickets"]["total"]
    all_total = (await client.get("/api/v1/dashboard/summary", headers=both)).json()["tickets"]["total"]
    assert 0 < in_total < all_total
    breakdown = (await client.get("/api/v1/dashboard/breakdowns", headers=india)).json()
    assert {r["key"] for r in breakdown["region"]} == {"IN"}


async def test_processing_monitor_reflects_stored_state(data, client, make_user):
    headers = await _login(client, make_user, (RoleName.AGENT_L1,))
    status = (await client.get("/api/v1/processing/PN-101129/status", headers=headers)).json()
    stages = {s["stage"]: s for s in status["stages"]}
    assert list(stages) == [
        "ingestion", "pii_redaction", "normalization", "customer_lookup", "classification", "deduplication",
        "routing", "retrieval", "answer_generation", "validation", "human_approval",
    ]  # fmt: skip
    assert "block" in stages["routing"]["detail"]
    assert stages["answer_generation"]["status"] == "not_run"  # blocked ticket: no AI draft, nothing pretended
    assert stages["human_approval"]["status"] == "pending"
    overview = (await client.get("/api/v1/processing/overview", headers=headers)).json()
    counts = {s["stage"]: s["counts"] for s in overview["stages"]}
    assert counts["routing"]["routed"] == overview["tickets"]
    assert counts["classification"]["not_run"] == overview["tickets"]


async def test_settings_are_bounded_audited_and_take_effect(data, client, make_user):
    lead = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    admin = await _login(client, make_user, (RoleName.ADMIN,))
    view = (await client.get("/api/v1/settings", headers=lead)).json()
    assert len(view["routing_rules"]) == 9 and view["models"]["classifier_model_id"] == "not configured"
    body = json.dumps(view)
    assert os.environ["PII_VAULT_KEY"] not in body and os.environ["JWT_SECRET"] not in body
    assert (
        await client.patch("/api/v1/settings", json={"dedupe.incident_min_tickets": 6}, headers=lead)
    ).status_code == 403
    assert (
        await client.patch("/api/v1/settings", json={"dedupe.incident_min_tickets": 31}, headers=admin)
    ).status_code == 422
    assert (
        await client.patch("/api/v1/settings", json={"routing.auto_answer_enabled": True}, headers=admin)
    ).status_code == 422
    assert (await client.patch("/api/v1/settings", json={"unknown.key": 1}, headers=admin)).status_code == 422

    changed = (
        await client.patch("/api/v1/settings", json={"dedupe.incident_min_tickets": 31 - 25}, headers=admin)
    ).json()
    assert changed["applied"] == {"dedupe.incident_min_tickets": {"from": 5, "to": 6}}
    detect = (await client.post("/api/v1/duplicates/detect", headers=admin)).json()
    assert detect["incidents"] == 1  # Kestrel's 5-ticket burst no longer qualifies at 6; Meridian (30) still does
    await client.patch("/api/v1/settings", json={"dedupe.incident_min_tickets": 5}, headers=admin)
    assert (await client.post("/api/v1/duplicates/detect", headers=admin)).json()["incidents"] == 2
    async with get_sessionmaker()() as session:
        audited = await session.scalar(text("SELECT count(*) FROM audit_logs WHERE action = 'settings.updated'"))
    assert audited == 2
