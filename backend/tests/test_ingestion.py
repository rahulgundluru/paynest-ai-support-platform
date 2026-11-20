"""End-to-end ingestion over the real (synthetic) case data. Requires data/source (scripts/source_data.py fetch).

These tests are the Phase 2 acceptance criteria:
- every record is accounted for; duplicates are reported, not dropped; re-runs are idempotent
- G1 (deterministic part): no PII value from the source appears anywhere in stored plaintext
- SLA engine reproduces every credit on Finance's breach list
- customer resolution and region scoping behave as documented
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.db.session import get_sessionmaker
from app.models.identity import Region, RoleName
from app.models.tickets import NormalizationLog, PiiVaultEntry, SourceRecord, Ticket
from app.services.ingestion.pipeline import run_ingestion
from app.services.normalization.rules import CATEGORY_QUEUE
from app.services.pii import vault
from app.services.pii.detectors import DETECTORS
from app.services.pii.gate import contains_pii

SOURCE = Path(os.environ["DATA_SOURCE_DIR"])
pytestmark = [
    pytest.mark.ingested,
    pytest.mark.skipif(not (SOURCE / "data-room").is_dir(), reason="source data not fetched"),
]

PLAINTEXT_TABLES = {
    "tickets": (
        "concat_ws(' ', subject_redacted, body_redacted, (attributes - 'fingerprint')::text, review_reasons::text)"
    ),
    "ticket_messages": "body_redacted",
    "ticket_events": "data::text",
    "normalization_log": "coalesce(original_value, '') || ' ' || coalesce(normalized_value, '')",
    "pii_detections": "token || ' ' || field",
    "ingestion_batches": "summary::text",
    "audit_logs": "details::text",
    "source_records": "status_reasons::text",
}


@pytest.fixture(scope="module")
async def batch():
    async with get_sessionmaker()() as session:
        await session.execute(text("TRUNCATE users, ingestion_batches, customers, agents CASCADE"))
        await session.commit()
        return await run_ingestion(session, SOURCE)


def _source_pii_values() -> set[str]:
    values: set[str] = set()
    for rel in ("data-room/data/tickets_export.json", "data-room/data/whatsapp_export.json",
                "data-room/data/call_center_notes.json"):  # fmt: skip
        raw = (SOURCE / rel).read_text(encoding="utf-8")
        for detector in DETECTORS:
            for m in detector.pattern.finditer(raw):
                value = m.group(detector.group)
                if detector.method != "regex+checksum_required" and (
                    len(re.sub(r"\D", "", value)) >= 8 or "@" in value
                ):
                    values.add(value)
    return values


async def test_every_record_is_accounted_for(batch):
    s = batch.summary["sources"]
    export = s["data-room/data/tickets_export.json"]
    assert export["read"] == 1367
    assert export["processed"] + export.get("requires_review", 0) + export["duplicate"] == 1367
    assert export["duplicate"] + export.get("requires_review", 0) == 14  # 14 repeated ticket ids
    assert s["data-room/data/whatsapp_export.json"]["read"] == 112
    assert s["data-room/data/call_center_notes.json"]["read"] == 61
    assert batch.summary["totals"].get("failed", 0) == 0
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(SourceRecord)) == 1540
        export_tickets = await session.scalar(
            select(func.count()).where(Ticket.channel.in_(["email", "widget", "partner_portal"]))
        )
        assert export_tickets == 1353  # unique ticket ids in the export


async def test_conflicting_duplicates_go_to_review_not_overwrite(batch):
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(SourceRecord.external_id, SourceRecord.status, SourceRecord.status_reasons).where(
                    SourceRecord.status.in_(["duplicate", "requires_review"]),
                    SourceRecord.channel != "whatsapp",
                    SourceRecord.channel != "phone",
                )
            )
        ).all()
    assert len(rows) == 14
    assert all(r.status == "duplicate" or r.status_reasons == ["conflicting_duplicate_external_id"] for r in rows)


async def test_reingestion_is_idempotent(batch):
    async with get_sessionmaker()() as session:
        again = await run_ingestion(session, SOURCE)
        assert again.summary["totals"] == {"read": 1540, "skipped": 1540}
        assert await session.scalar(select(func.count()).select_from(SourceRecord)) == 1540


async def test_g1_no_source_pii_value_in_any_stored_plaintext(batch):
    values = _source_pii_values()
    assert len(values) > 100  # sanity: the source really contains PII
    async with get_sessionmaker()() as session:
        for table, expr in PLAINTEXT_TABLES.items():
            texts = (await session.scalars(text(f"SELECT {expr} FROM {table}"))).all()  # noqa: S608 (constant SQL)
            blob = "\n".join(t or "" for t in texts)
            leaked = [v for v in values if v in blob]
            assert not leaked, f"{table}: {len(leaked)} raw PII values found"
            assert not any(contains_pii(t) for t in texts), f"{table}: a detector still matches stored text"


async def test_pii_is_recoverable_only_from_the_encrypted_vault(batch):
    async with get_sessionmaker()() as session:
        entry = await session.scalar(select(PiiVaultEntry).where(PiiVaultEntry.entity_type == "IBAN").limit(1))
        assert entry is not None
        assert b"AE" not in entry.value_encrypted
        assert vault.decrypt(entry.value_encrypted).startswith("AE")


async def test_free_text_pii_ticket_count_is_stable(batch):
    # Discovery measured 103 export tickets with ID/bank PII (session notes say 101; see docs).
    records = batch.summary["pii"]["records_with_pii_in_free_text"]
    async with get_sessionmaker()() as session:
        export_with_id_pii = await session.scalar(
            text(
                "SELECT count(DISTINCT t.id) FROM tickets t JOIN pii_detections d ON d.ticket_id = t.id "
                "WHERE t.channel IN ('email','widget','partner_portal') AND d.field IN ('subject','body') "
                "AND d.entity_type IN ('AADHAAR','PAN','IBAN','EMIRATES_ID','IFSC','BANK_ACCOUNT')"
            )
        )
    assert export_with_id_pii == 103
    assert records["data-room/data/whatsapp_export.json"] > 0


async def test_customer_resolution_rules(batch):
    async with get_sessionmaker()() as session:
        counts = dict(
            (
                await session.execute(
                    select(Ticket.channel + ":" + Ticket.customer_resolution, func.count()).group_by(
                        Ticket.channel, Ticket.customer_resolution
                    )
                )
            ).all()
        )
    assert counts["partner_portal:partner_end_customer_name"] == 65  # every null-tenant ticket, exact name
    assert counts["whatsapp:unresolved"] == 57  # no customer hint: manual verification, never guessed
    assert counts["phone:unresolved"] == 7
    assert "email:unresolved" not in counts and "widget:unresolved" not in counts


async def test_original_pick_routes_to_first_queue_and_label_leak_is_isolated(batch):
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(
                    Ticket.customer_category, Ticket.first_queue, Ticket.final_category_label, Ticket.final_queue
                ).where(Ticket.first_queue.is_not(None))
            )
        ).all()
    assert len(rows) == 1327
    assert all(CATEGORY_QUEUE[r.customer_category] == r.first_queue for r in rows)
    assert all(CATEGORY_QUEUE[r.final_category_label] == r.final_queue for r in rows)
    assert sum(1 for r in rows if r.first_queue != r.final_queue) == 201


async def test_timestamps_and_derived_first_response(batch):
    async with get_sessionmaker()() as session:
        in_window = await session.scalar(
            select(func.count()).where(
                Ticket.channel.in_(["email", "widget", "partner_portal"]), Ticket.in_payroll_window
            )
        )
        derived = await session.scalar(
            select(func.count()).where(
                NormalizationLog.field == "first_response_at", NormalizationLog.rule == "FR_DERIVED_FROM_REPLY_EVENT"
            )
        )
    assert in_window == 951  # 70.3 % of 1,353
    assert derived == 80


async def _login(client, make_user, roles, regions):
    email = f"u{uuid.uuid4().hex[:8]}@paynest.test"
    _, password = await make_user(email=email, roles=roles, regions=regions)
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    client.cookies.clear()
    return {"Authorization": f"Bearer {token['access_token']}"}


async def test_sla_engine_reproduces_every_finance_credit(batch, client, make_user):
    headers = await _login(client, make_user, (RoleName.FINANCE_VIEWER,), (Region.IN, Region.UAE))
    report = (await client.get("/api/v1/sla/reconciliation", headers=headers)).json()
    assert report["finance_rows"] == 128
    assert report["matched"] == 128, [r for r in report["rows"] if not r["matches"]][:3]
    assert report["finance_total_usd"] == report["engine_total_for_finance_rows_usd"] == "19195.95"


async def test_region_scoping_hides_other_region(batch, client, make_user):
    india = await _login(client, make_user, (RoleName.AGENT_L1,), (Region.IN,))
    page = (await client.get("/api/v1/tickets?region=UAE", headers=india)).json()
    assert page["total"] == 0
    listing = (await client.get("/api/v1/tickets?page_size=200", headers=india)).json()
    assert {t["region"] for t in listing["items"]} == {"IN"}
    # PN-101333 belongs to a UAE customer: an India-scoped user cannot tell it exists
    assert (await client.get("/api/v1/tickets/PN-101333", headers=india)).status_code == 404
    # tickets with unknown region are only visible to all-region users
    unknown = (await client.get("/api/v1/tickets?channel=whatsapp&page_size=200", headers=india)).json()
    assert all(t["region"] == "IN" for t in unknown["items"])


async def test_ticket_detail_exposes_tokens_never_values(batch, client, make_user):
    headers = await _login(client, make_user, (RoleName.SUPPORT_LEAD,), (Region.IN, Region.UAE))
    detail = (await client.get("/api/v1/tickets/PN-101333", headers=headers)).json()
    assert "<IBAN_1>" in detail["body_redacted"] and "<EMIRATES_ID_1>" in detail["body_redacted"]
    assert {d["entity_type"] for d in detail["pii_detections"]} >= {"IBAN", "EMIRATES_ID"}
    assert not contains_pii(json.dumps(detail, ensure_ascii=False))
    assert detail["sla"] is not None and detail["customer_resolution"] == "direct"
    timeline = (await client.get("/api/v1/tickets/PN-101333/timeline", headers=headers)).json()
    assert timeline[0]["type"] in {"created", "customer"}


async def test_rbac_on_phase2_endpoints(batch, client, make_user):
    finance = await _login(client, make_user, (RoleName.FINANCE_VIEWER,), (Region.IN,))
    assert (await client.get("/api/v1/tickets", headers=finance)).status_code == 403
    assert (await client.post("/api/v1/processing/ingest", headers=finance)).status_code == 403
    agent = await _login(client, make_user, (RoleName.AGENT_L1,), (Region.IN,))
    assert (await client.get("/api/v1/sla/reconciliation", headers=agent)).status_code == 403
    customers = (await client.get("/api/v1/customers?page_size=200", headers=agent)).json()
    assert customers["total"] == 42 and {c["region"] for c in customers["items"]} == {"IN"}
