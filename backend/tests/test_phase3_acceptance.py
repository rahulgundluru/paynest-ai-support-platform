"""Phase 3 acceptance on the real (synthetic) case data: knowledge validity, date-aware retrieval (G5
deterministic part), duplicate/incident detection (G3), deterministic routing and injection blocking (G4)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import get_sessionmaker
from app.models.identity import Region, RoleName
from app.services.deduplication.service import run_detection
from app.services.ingestion.pipeline import run_ingestion
from app.services.knowledge.ingest import index_knowledge
from app.services.knowledge.retrieval import retrieve, statutory_rates
from app.services.normalization.timestamps import IST
from app.services.routing.service import route_all

SOURCE = Path(os.environ["DATA_SOURCE_DIR"])
STALE_KB = {"KB-0142", "KB-0143", "KB-0201", "KB-0202"}
pytestmark = [
    pytest.mark.ingested,
    pytest.mark.skipif(not (SOURCE / "data-room").is_dir(), reason="source data not fetched"),
]


@pytest.fixture(scope="module")
async def pipeline():
    async with get_sessionmaker()() as session:
        await session.execute(
            text("TRUNCATE users, ingestion_batches, customers, agents, knowledge_documents, statutory_rules CASCADE")
        )
        await session.commit()
        await run_ingestion(session, SOURCE)
        kb = await index_knowledge(session, SOURCE)
        dedupe = await run_detection(session)
        routing = await route_all(session)
    return {"kb": kb, "dedupe": dedupe, "routing": routing}


async def _login(client, make_user, roles, regions):
    email = f"u{uuid.uuid4().hex[:8]}@paynest.test"
    _, password = await make_user(email=email, roles=roles, regions=regions)
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    client.cookies.clear()
    return {"Authorization": f"Bearer {token['access_token']}"}


async def test_knowledge_index_is_idempotent_and_never_uses_last_reviewed_as_effective_date(pipeline):
    assert pipeline["kb"]["documents"] == 32  # 4 rules + 24 KB articles + 4 process documents
    async with get_sessionmaker()() as session:
        again = await index_knowledge(session, SOURCE)
        assert again["versions_created"] == 0
        rows = (
            await session.execute(
                text(
                    "SELECT d.id, v.effective_from, v.effective_to, v.validity_source, v.content_complete "
                    "FROM knowledge_document_versions v JOIN knowledge_documents d ON d.id = v.document_id "
                    "WHERE d.doc_type = 'kb_article'"
                )
            )
        ).all()
    windows = {r.id: (r.effective_to, r.validity_source) for r in rows}
    assert all(r.effective_from is None for r in rows)
    assert windows["KB-0142"] == (date(2026, 7, 31), "derived:R-IN-PF-2026-08")
    assert windows["KB-0202"] == (date(2026, 7, 14), "derived:R-UAE-WPS-2026-07")
    assert windows["KB-0150"] == (None, "not_stated_in_source")  # reviewed after the TDS change took effect
    assert sum(1 for r in rows if r.content_complete) == 4  # only four articles have any text in the source


@pytest.mark.parametrize(
    ("as_of", "expected", "stale_allowed"),
    [(date(2026, 6, 15), "INR 15,000", True), (date(2026, 9, 15), "INR 25,000", False)],
)
async def test_g5_pf_ceiling_follows_the_question_date(pipeline, as_of, expected, stale_allowed):
    async with get_sessionmaker()() as session:
        _, hits = await retrieve(session, "What is the current PF wage ceiling?", region="IN", as_of=as_of, limit=5)
        rates = {r.rule_id: r.value for r in await statutory_rates(session, "IN", as_of)}
    rule_hit = next(h for h in hits if h.document_id == "R-IN-PF-2026-08")
    assert expected in rule_hit.text
    assert ("KB-0142" in {h.document_id for h in hits}) is stale_allowed
    assert rates["R-IN-PF-2026-08"].startswith(expected)


async def test_g5_zero_stale_chunks_for_the_48_stale_citation_tickets(pipeline):
    query = (
        "SELECT DISTINCT t.id, t.region, t.subject_redacted, t.body_redacted, e.occurred_at "
        "FROM tickets t JOIN ticket_events e ON e.ticket_id = t.id WHERE e.event_type = 'replied' AND ("
        "(e.data->>'kb_article_id' IN ('KB-0142','KB-0143') AND e.occurred_at >= '2026-08-01T00:00:00+05:30') OR "
        "(e.data->>'kb_article_id' IN ('KB-0201','KB-0202') AND e.occurred_at >= '2026-07-15T00:00:00+05:30'))"
    )
    async with get_sessionmaker()() as session:
        stale = (await session.execute(text(query))).all()
        assert len(stale) == 48
        bad = 0
        for t in stale:
            as_of = t.occurred_at.astimezone(IST).date()
            _, hits = await retrieve(
                session, f"{t.subject_redacted or ''} {t.body_redacted or ''}", region=t.region, as_of=as_of, limit=8
            )
            bad += sum(
                1
                for h in hits
                if h.document_id in STALE_KB
                or (h.effective_to and h.effective_to < as_of)
                or (h.effective_from and h.effective_from > as_of)
            )
    assert bad == 0


async def test_g3_resubmissions_and_meridian_incident(pipeline):
    assert pipeline["dedupe"]["resubmission_links"] == 26
    truth_sql = (
        "SELECT t.external_id, split_part(e.data->>'resolution', ' ', 3) FROM ticket_events e "
        "JOIN tickets t ON t.id = e.ticket_id WHERE e.data->>'resolution' LIKE 'duplicate of%'"
    )
    predicted_sql = (
        "SELECT c.external_id, p.external_id, l.confidence FROM incident_links l "
        "JOIN incidents i ON i.id = l.incident_id JOIN tickets c ON c.id = l.ticket_id "
        "JOIN tickets p ON p.id = i.master_ticket_id WHERE l.role = 'resubmit'"
    )
    meridian_sql = (
        "SELECT count(*), min(t.created_at), i.declared_at FROM incidents i "
        "JOIN incident_links l ON l.incident_id = i.id JOIN tickets t ON t.id = l.ticket_id "
        "WHERE i.kind = 'incident' AND i.customer_id = 'C-1002' GROUP BY i.id"
    )
    async with get_sessionmaker()() as session:
        truth = dict((await session.execute(text(truth_sql))).all())
        predicted = (await session.execute(text(predicted_sql))).all()
        count, first_at, declared_at = (await session.execute(text(meridian_sql))).one()
    correct = [p for p in predicted if truth.get(p[0]) == p[1]]
    wrong = [p for p in predicted if truth.get(p[0]) != p[1]]
    assert len(truth) == 26 and len(correct) == 25  # precision 25/26, recall 25/26
    assert all(p[2] < 0.9 for p in wrong)  # the one miss was flagged ambiguous for a person to confirm
    assert count == 30
    assert (declared_at - first_at).total_seconds() < 30 * 60  # declared at the 5th ticket


async def test_routing_records_every_ticket_and_blocks_injection(pipeline, client, make_user):
    assert sum(pipeline["routing"]["lanes"].values()) == 1526
    headers = await _login(client, make_user, (RoleName.SUPPORT_LEAD,), (Region.IN, Region.UAE))
    result = (await client.post("/api/v1/tickets/PN-101129/process", headers=headers)).json()
    assert result["classification"]["status"] == "unavailable"  # no model configured: nothing is guessed
    assert result["routing"]["lane"] == "block" and result["routing"]["rule_id"] == "R1"
    routing = (await client.get("/api/v1/tickets/PN-101234/routing", headers=headers)).json()
    assert routing["incidents"][0]["kind"] == "incident" and routing["incidents"][0]["ticket_count"] == 30


async def test_manual_unlink_is_permissioned_and_survives_redetection(pipeline, client, make_user):
    lead = await _login(client, make_user, (RoleName.SUPPORT_LEAD,), (Region.IN, Region.UAE))
    agent = await _login(client, make_user, (RoleName.AGENT_L1,), (Region.IN,))
    page = (await client.get("/api/v1/duplicates?kind=incident&customer_id=C-1002", headers=lead)).json()
    incident_id = page["items"][0]["id"]
    detail = (await client.get(f"/api/v1/duplicates/{incident_id}", headers=lead)).json()
    member = next(link["external_id"] for link in detail["links"] if link["role"] == "member")
    url = f"/api/v1/duplicates/{incident_id}"
    assert (await client.post(f"{url}/unlink", json={"ticket_ref": member}, headers=agent)).status_code == 403
    after = (await client.post(f"{url}/unlink", json={"ticket_ref": member}, headers=lead)).json()
    assert after["ticket_count"] == 29
    cross = await client.post(f"{url}/link", json={"ticket_ref": "PN-101333"}, headers=lead)
    assert cross.status_code == 422  # a different customer's ticket is never grouped
    async with get_sessionmaker()() as session:
        await run_detection(session)
        kept = await session.scalar(
            text("SELECT count(*) FILTER (WHERE active) FROM incident_links WHERE incident_id = :i"),
            {"i": incident_id},
        )
    assert kept == 29


async def test_knowledge_search_redacts_query_and_hides_stale_articles(pipeline, client, make_user):
    headers = await _login(client, make_user, (RoleName.AGENT_L1,), (Region.IN,))
    body = {"query": "PF ceiling for PAN ABCDE0021F, we used KB-0142", "region": "IN", "as_of": "2026-09-10"}
    result = (await client.post("/api/v1/knowledge/search", json=body, headers=headers)).json()
    assert "<PAN_1>" in result["query_redacted"] and "ABCDE0021F" not in str(result)
    assert "KB-0142" not in {h["document_id"] for h in result["hits"]}
    rates = (await client.get("/api/v1/statutory/rates?region=IN&as_of=2026-06-01", headers=headers)).json()
    assert {r["rule_id"]: r["value"] for r in rates}["R-IN-PF-2026-08"] == "INR 15,000 per month"
