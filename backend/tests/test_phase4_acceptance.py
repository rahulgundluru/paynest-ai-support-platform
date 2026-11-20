"""Phase 4 acceptance on the real data: review queue, validated approvals with a two-person rule,
blocked injection, learned memory from human-approved replies only, audited DPO-only PII reveal."""

from __future__ import annotations

import os
import uuid
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
async def queue():
    async with get_sessionmaker()() as session:
        await session.execute(
            text("TRUNCATE users, ingestion_batches, customers, agents, knowledge_documents, statutory_rules CASCADE")
        )
        await session.commit()
        await run_ingestion(session, SOURCE)
        await index_knowledge(session, SOURCE)
        await run_detection(session)
        await route_all(session)
        return await build_review_queue(session)


async def _login(client, make_user, roles, regions=BOTH):
    email = f"u{uuid.uuid4().hex[:8]}@paynest.test"
    _, password = await make_user(email=email, roles=roles, regions=regions)
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    client.cookies.clear()
    return {"Authorization": f"Bearer {token['access_token']}"}


async def _approval_for(client, headers, ext_id):
    page = (await client.get("/api/v1/approvals?status=all&page_size=100", headers=headers)).json()
    while True:
        match = next((a for a in page["items"] if a["ticket_external_id"] == ext_id), None)
        if match or page["page"] * page["page_size"] >= page["total"]:
            return match
        page = (
            await client.get(f"/api/v1/approvals?status=all&page_size=100&page={page['page'] + 1}", headers=headers)
        ).json()


async def test_review_queue_contains_every_ticket_that_needs_a_person(queue):
    assert queue["review_items_created"] == 288
    async with get_sessionmaker()() as session:
        by_rule = dict((await session.execute(text("SELECT rule_id, count(*) FROM approvals GROUP BY rule_id"))).all())
        again = await build_review_queue(session)
    assert by_rule == {"R1": 1, "R2": 64, "R5": 109, "R6": 28, "R7": 86}
    assert again["review_items_created"] == 0  # idempotent


async def test_statutory_draft_must_pass_validation_and_a_second_person(queue, client, make_user):
    async with get_sessionmaker()() as session:
        ext_id = await session.scalar(
            text(
                "SELECT t.external_id FROM approvals a JOIN tickets t ON t.id = a.ticket_id WHERE a.rule_id = 'R7' "
                "AND t.region = 'IN' AND t.created_at >= '2026-08-02' ORDER BY t.created_at LIMIT 1"
            )
        )
    author = await _login(client, make_user, (RoleName.AGENT_L2,))
    approver = await _login(client, make_user, (RoleName.AGENT_L2,))
    l1 = await _login(client, make_user, (RoleName.AGENT_L1,))
    item = await _approval_for(client, author, ext_id)
    url = f"/api/v1/approvals/{item['id']}"
    detail = (await client.get(url, headers=author)).json()
    assert detail["evidence"]["summary"] and detail["requires_second_person"]
    assert any(r["value"] == "INR 25,000 per month" for r in detail["evidence"]["statutory_rates_in_force"])
    assert all(k["document_id"] not in {"KB-0142", "KB-0143"} for k in detail["evidence"]["knowledge_in_force"])

    stale = (
        await client.put(
            f"{url}/draft", json={"text": "The ceiling is INR 15,000 per month (KB-0142)."}, headers=author
        )
    ).json()
    assert stale["validation"]["passed"] is False
    assert (await client.post(f"{url}/decision", json={"action": "approve"}, headers=approver)).status_code == 422
    assert (await client.post(f"{url}/decision", json={"action": "approve"}, headers=l1)).status_code == 403

    good = "From 1 Aug 2026 the EPF wage ceiling is INR 25,000 per month (R-IN-PF-2026-08)."
    assert (await client.put(f"{url}/draft", json={"text": good}, headers=author)).json()["validation"]["passed"]
    same_person = await client.post(f"{url}/decision", json={"action": "approve"}, headers=author)
    assert same_person.status_code == 403  # two-person rule
    approved = (
        await client.post(f"{url}/decision", json={"action": "approve", "note": "checked"}, headers=approver)
    ).json()
    assert approved["status"] == "approved"
    assert [e["action"] for e in approved["events"]] == ["created", "edited", "edited", "approved"]
    assert (await client.post(f"{url}/decision", json={"action": "reject"}, headers=approver)).status_code == 409

    memory = (await client.get("/api/v1/memory?include_expired=true", headers=approver)).json()
    entry = next(m for m in memory["items"] if m["resolution_text"] == good)
    assert entry["cited_versions"] == [{"document_id": "R-IN-PF-2026-08", "version": 2}]
    async with get_sessionmaker()() as session:
        actions = set(
            (await session.scalars(text("SELECT action FROM audit_logs WHERE entity_id = :i"), {"i": item["id"]})).all()
        )
    assert {"approval.edited", "approval.approve"} <= actions


async def test_blocked_injection_cannot_be_approved_only_resolved_or_escalated(queue, client, make_user):
    lead = await _login(client, make_user, (RoleName.SUPPORT_LEAD,))
    item = await _approval_for(client, lead, "PN-101129")
    assert item["lane"] == "block" and item["queue"] == "Security-Review"
    url = f"/api/v1/approvals/{item['id']}"
    detail = (await client.get(url, headers=lead)).json()
    assert detail["evidence"]["injection_signals"]
    await client.put(f"{url}/draft", json={"text": "Thanks, we are looking into your refund status."}, headers=lead)
    assert (await client.post(f"{url}/decision", json={"action": "approve"}, headers=lead)).status_code == 409
    assert (await client.post(f"{url}/decision", json={"action": "resolve"}, headers=lead)).status_code == 422
    done = await client.post(
        f"{url}/decision", json={"action": "escalate", "target": "SECURITY", "note": "prompt injection"}, headers=lead
    )
    assert done.json()["status"] == "escalated"


async def test_unapproved_items_never_become_memory(queue):
    async with get_sessionmaker()() as session:
        orphan = await session.scalar(
            text(
                "SELECT count(*) FROM learned_memory m JOIN approvals a ON a.id = m.approval_id "
                "WHERE a.status <> 'approved'"
            )
        )
    assert orphan == 0


async def test_pii_reveal_is_dpo_only_and_audited_without_the_value(queue, client, make_user):
    dpo = await _login(client, make_user, (RoleName.DPO,))
    admin = await _login(client, make_user, (RoleName.ADMIN,))
    url = "/api/v1/tickets/PN-101333/pii/IBAN_1/reveal"
    body = {"reason": "Customer data access request DSR-0001"}
    assert (await client.post(url, json=body, headers=admin)).status_code == 403
    assert (await client.post(url, json={"reason": "short"}, headers=dpo)).status_code == 422
    revealed = (await client.post(url, json=body, headers=dpo)).json()
    assert revealed["entity_type"] == "IBAN" and revealed["value"].startswith("AE")
    async with get_sessionmaker()() as session:
        details = (
            await session.scalars(text("SELECT details::text FROM audit_logs WHERE action = 'pii.revealed'"))
        ).all()
    assert details and all(revealed["value"] not in d and "DSR-0001" in d for d in details)
    assert (await client.post("/api/v1/tickets/PN-101333/pii/IBAN_9/reveal", json=body, headers=dpo)).status_code == 404
