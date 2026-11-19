"""Ingestion pipeline: source record -> PII gate -> normalization -> customer/SLA lookup -> persist.

Guarantees:
- Every record read produces a `source_records` row (processed, requires_review, duplicate, failed)
  or is counted as `skipped` because the identical record was already ingested. Nothing is dropped.
- The PII gate runs before anything except the encrypted raw record is written.
- Re-running over the same source files is a no-op (idempotent on file + index + content hash).
- Each record is processed in its own savepoint, so one bad record cannot abort the batch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import Customer, SlaTerm
from app.models.tickets import (
    EVENT_TYPES,
    IngestionBatch,
    NormalizationLog,
    PiiDetection,
    PiiVaultEntry,
    SlaTracking,
    SourceRecord,
    Ticket,
    TicketEvent,
    TicketMessage,
)
from app.services import audit
from app.services.customer_lookup import CustomerDirectory
from app.services.ingestion.adapters import (
    CALLS_FILE,
    EXPORT_FILE,
    WHATSAPP_FILE,
    SourceTicket,
    parse_calls,
    parse_export,
    parse_whatsapp,
)
from app.services.ingestion.reference import load_reference, sha256_file
from app.services.normalization import rules
from app.services.normalization.timestamps import TimestampError, in_payroll_window, parse_timestamp
from app.services.pii import vault
from app.services.pii.gate import PiiGate, RedactionResult
from app.services.sla.engine import RULE_VERSION, SlaTerms, evaluate

log = logging.getLogger(__name__)

EXPORT_CHANNELS = {"email", "widget", "partner_portal"}
SOURCES: tuple[tuple[str, Callable[[Any], Iterator[SourceTicket]]], ...] = (
    (EXPORT_FILE, parse_export),
    (WHATSAPP_FILE, parse_whatsapp),
    (CALLS_FILE, parse_calls),
)


class SourceDataMissing(FileNotFoundError):
    pass


@dataclass
class _Outcome:
    status: str
    reasons: list[str] = field(default_factory=list)
    pii_entities: Counter[str] = field(default_factory=Counter)
    free_text_pii: Counter[str] = field(default_factory=Counter)


@dataclass
class _NormLog:
    field: str
    original: str | None
    normalized: str | None
    rule: str


def _language_hint(text: str | None) -> str | None:
    if not text:
        return None
    if re.search(r"[؀-ۿ]", text):
        return "ar"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    return "latin"  # English or romanised Hindi; real language detection happens at classification


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class IngestionRun:
    def __init__(self, session: AsyncSession, source_dir: Path, now: datetime, retention_days: int) -> None:
        self.session = session
        self.source_dir = source_dir
        self.now = now
        self.retention_until = now + timedelta(days=retention_days)
        self.summary: dict[str, Any] = {}

    async def prepare(self) -> None:
        customers = list(await self.session.scalars(select(Customer)))
        self.directory = CustomerDirectory(customers)
        self.terms = {
            (t.tier, t.priority): SlaTerms(t.template_version, t.first_response_h, t.resolution_h, t.credit_pct)
            for t in await self.session.scalars(select(SlaTerm).where(SlaTerm.template_version == "v3.2"))
        }
        self.existing_records = {
            (r.source_file, r.record_index): r.record_hash for r in await self.session.scalars(select(SourceRecord))
        }
        self.seen_tickets: dict[str, tuple[int, str]] = {
            t.external_id: (t.source_record_id, t.attributes.get("fingerprint", ""))
            for t in await self.session.scalars(select(Ticket).where(Ticket.external_id.is_not(None)))
            if t.external_id
        }

    # ------------------------------------------------------------------ per record
    async def process(self, st: SourceTicket, batch_id: uuid.UUID, file_sha: str) -> _Outcome:
        record = SourceRecord(
            batch_id=batch_id,
            source_file=st.source_file,
            source_sha256=file_sha,
            record_index=st.record_index,
            record_hash=st.record_hash,
            external_id=st.external_id,
            channel=st.channel,
            status="processing",
            raw_encrypted=vault.encrypt(json.dumps(st.raw, ensure_ascii=False)),
        )
        self.session.add(record)
        await self.session.flush()

        # 1. PII gate: everything below sees redacted text only.
        text_fields: dict[str, str | None] = {"subject": st.subject, "body": st.body, **st.contact_fields}
        for i, m in enumerate(st.messages):
            text_fields[f"message[{i}]"] = m.text
        for i, raw_event in enumerate(st.events):
            for key in ("reason", "note"):
                if isinstance(raw_event.data.get(key), str):
                    text_fields[f"event[{i}].{key}"] = raw_event.data[key]
        redaction = PiiGate().redact(text_fields)

        # 2. Normalization.
        logs: list[_NormLog] = []
        reasons: list[str] = []
        events = self._normalize_events(st, redaction, logs, reasons)
        created_at = self._created_at(st, events, logs)
        first_response_at = self._first_response_at(st, events, logs)
        resolved_at = self._resolved_at(st, events, logs)

        if st.channel in EXPORT_CHANNELS:
            pr = rules.map_priority(st.channel, st.priority_raw)
            created_event = next((e for e in events if e["event_type"] == "created"), None)
            cat = rules.map_category(created_event["data"].get("category") if created_event else None)
            final_label = rules.map_category(st.final_category_raw)
            logs.append(_NormLog("final_category_label", st.final_category_raw, final_label.value, final_label.rule))
        else:
            pr = rules.Mapped(None, "PRIORITY_NOT_PROVIDED_BY_CHANNEL")
            cat = rules.Mapped(None, "CATEGORY_NOT_PROVIDED_BY_CHANNEL")
            final_label = rules.Mapped(None, "CATEGORY_NOT_PROVIDED_BY_CHANNEL")
        logs.append(_NormLog("priority", st.priority_raw, pr.value, pr.rule))
        logs.append(_NormLog("customer_category", None, cat.value, cat.rule))
        status = (
            rules.map_status(st.status_raw)
            if st.channel != "phone"
            else rules.Mapped(None, "STATUS_NOT_PROVIDED_BY_CHANNEL")
        )
        logs.append(_NormLog("status", st.status_raw, status.value, status.rule))
        for mapped, reason in ((pr, "priority"), (cat, "category"), (status, "status")):
            if mapped.value is None and mapped.rule.endswith(("UNKNOWN_LABEL", "UNKNOWN_VALUE", "MISSING")):
                reasons.append(f"{reason}_{mapped.rule.split('_', 1)[1].lower()}")
        if pr.value is None and pr.rule == "PRIORITY_NOT_PROVIDED_BY_CHANNEL":
            reasons.append("priority_not_provided_by_channel")

        # 3. Customer lookup (deterministic) and region.
        resolution = self.directory.resolve(
            st.channel, st.customer_id, st.customer_name_hint, st.contact_fields.get("wa_contact")
        )
        logs.append(
            _NormLog(
                "customer_id",
                st.customer_id or (f"name:{st.customer_name_hint}" if st.customer_name_hint else None),
                resolution.customer.customer_id if resolution.customer else None,
                f"CUSTOMER_{resolution.method.upper()}",
            )
        )
        if resolution.customer is None:
            reasons.append(resolution.reason or "customer_unresolved")
        record.region = resolution.region

        # 4. Queues and history metrics.
        queues = [e["data"].get("queue") for e in events if e["event_type"] == "assigned"]
        first_queue = queues[0] if queues else None
        final_queue = first_queue
        reassignments = 0
        for ev in events:
            if ev["event_type"] == "reassigned":
                final_queue = ev["data"].get("to")
                if ev["data"].get("from") != ev["data"].get("to"):
                    reassignments += 1

        subject_r, body_r = redaction.fields.get("subject"), redaction.fields.get("body")
        fingerprint = _fingerprint(
            {
                "customer": resolution.customer.customer_id if resolution.customer else None,
                "created": created_at,
                "priority": pr.value,
                "category": cat.value,
                "final": final_label.value,
                "status": status.value,
                "subject": subject_r,
                "body": body_r,
                "events": [(e["event_type"], e["occurred_at"], e["actor"], e["data"]) for e in events],
            }
        )

        outcome = _Outcome(
            status="processed",
            pii_entities=Counter(redaction.entity_counts),
            free_text_pii=Counter(d.entity_type for d in redaction.detections if d.field not in st.contact_fields),
        )
        detections = self._store_pii(record, redaction, resolution.region)

        # 5. Duplicate handling (same external id seen before).
        if st.external_id and st.external_id in self.seen_tickets:
            first_record_id, first_fp = self.seen_tickets[st.external_id]
            if first_fp == fingerprint:
                record.status, record.duplicate_of_record_id = "duplicate", first_record_id
                record.status_reasons = ["identical_after_normalization"]
            else:
                record.status, record.status_reasons = "requires_review", ["conflicting_duplicate_external_id"]
            self._store_logs(record, None, logs)
            return _Outcome(record.status, record.status_reasons, outcome.pii_entities, outcome.free_text_pii)

        ticket = Ticket(
            external_id=st.external_id,
            source_record_id=record.id,
            channel=st.channel,
            customer_id=resolution.customer.customer_id if resolution.customer else None,
            customer_resolution=resolution.method,
            region=resolution.region,
            region_source=resolution.region_source,
            partner_id=st.partner_id,
            subject_redacted=subject_r,
            body_redacted=body_r,
            language_hint=_language_hint(body_r),
            priority=pr.value,
            customer_category=cat.value,
            final_category_label=final_label.value,
            first_queue=first_queue,
            final_queue=final_queue,
            status=status.value,
            created_at=created_at,
            first_response_at=first_response_at,
            resolved_at=resolved_at,
            reassignment_count=reassignments,
            reopen_count=sum(1 for e in events if e["event_type"] == "reopened"),
            in_payroll_window=in_payroll_window(created_at),
            ingestion_status="requires_review" if reasons else "processed",
            review_reasons=sorted(set(reasons)),
            attributes={
                **{k: v for k, v in st.attributes.items() if v is not None},
                **{f"{k}_token": redaction.fields[k] for k in st.contact_fields if redaction.fields.get(k)},
                "fingerprint": fingerprint,
            },
        )
        self.session.add(ticket)
        await self.session.flush()
        if st.external_id:
            self.seen_tickets[st.external_id] = (record.id, fingerprint)

        if st.channel in EXPORT_CHANNELS and body_r:
            self.session.add(
                TicketMessage(
                    ticket_id=ticket.id, seq=0, author_type="customer", sent_at=created_at, body_redacted=body_r
                )
            )
        for i, m in enumerate(st.messages):
            sent = parse_timestamp(m.sent_raw).value if m.sent_raw is not None else None
            self.session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    seq=i,
                    author_type=m.author_type,
                    sent_at=sent,
                    body_redacted=redaction.fields.get(f"message[{i}]") or "",
                )
            )
        for i, ev in enumerate(events):
            self.session.add(TicketEvent(ticket_id=ticket.id, seq=i, **ev))

        customer = resolution.customer
        sla = evaluate(
            tier=customer.tier if customer else None,
            priority=pr.value,
            created_at=created_at,
            first_response_at=first_response_at,
            resolved_at=resolved_at,
            monthly_fee_usd=customer.monthly_fee_usd if customer else None,
            terms=self.terms.get((customer.tier, pr.value)) if customer and pr.value else None,
            as_of=self.now,
        )
        self.session.add(
            SlaTracking(
                ticket_id=ticket.id,
                applicable=sla.applicable,
                not_applicable_reason=sla.not_applicable_reason,
                template_version=sla.template_version,
                tier=customer.tier if customer else None,
                priority=pr.value,
                first_response_target_h=sla.first_response_target_h,
                resolution_target_h=sla.resolution_target_h,
                first_response_due_at=sla.first_response_due_at,
                resolution_due_at=sla.resolution_due_at,
                first_response_hours=sla.first_response_hours,
                resolution_hours=sla.resolution_hours,
                first_response_breached=sla.first_response_breached,
                resolution_breached=sla.resolution_breached,
                severity_multiplier=sla.severity_multiplier,
                credit_pct=sla.credit_pct,
                credit_usd=sla.credit_usd,
                rule_version=RULE_VERSION,
            )
        )
        self._store_logs(record, ticket.id, logs)
        for detection in detections:
            detection.ticket_id = ticket.id
        record.status = ticket.ingestion_status
        record.status_reasons = ticket.review_reasons
        outcome.status, outcome.reasons = record.status, record.status_reasons
        return outcome

    # ------------------------------------------------------------------ helpers
    def _normalize_events(
        self, st: SourceTicket, redaction: RedactionResult, logs: list[_NormLog], reasons: list[str]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for i, e in enumerate(st.events):
            if e.event_type not in EVENT_TYPES:
                reasons.append("unknown_event_type")
                continue
            parsed = parse_timestamp(e.time_raw)
            data = dict(e.data)
            for key in ("reason", "note"):
                if f"event[{i}].{key}" in redaction.fields:
                    data[key] = redaction.fields[f"event[{i}].{key}"]
            if parsed.rule != "TS_ISO_OFFSET":
                logs.append(_NormLog(f"event[{i}].time", None, parsed.value.isoformat(), parsed.rule))
            events.append({"event_type": e.event_type, "occurred_at": parsed.value, "actor": e.actor, "data": data})
        return events

    def _created_at(self, st: SourceTicket, events: list[dict[str, Any]], logs: list[_NormLog]) -> datetime:
        created_event = next((e for e in events if e["event_type"] == "created"), None)
        if created_event:
            logs.append(_NormLog("created_at", None, created_event["occurred_at"].isoformat(), "CREATED_FROM_EVENT"))
            return created_event["occurred_at"]  # type: ignore[no-any-return]
        parsed = parse_timestamp(st.created_raw)
        logs.append(_NormLog("created_at", None, parsed.value.isoformat(), parsed.rule))
        return parsed.value

    def _first_response_at(
        self, st: SourceTicket, events: list[dict[str, Any]], logs: list[_NormLog]
    ) -> datetime | None:
        if st.first_response_raw not in (None, ""):
            parsed = parse_timestamp(st.first_response_raw)
            logs.append(_NormLog("first_response_at", None, parsed.value.isoformat(), parsed.rule))
            return parsed.value
        reply = next((e for e in events if e["event_type"] == "replied" and not e["data"].get("internal")), None)
        if reply:
            logs.append(
                _NormLog("first_response_at", None, reply["occurred_at"].isoformat(), "FR_DERIVED_FROM_REPLY_EVENT")
            )
            return reply["occurred_at"]  # type: ignore[no-any-return]
        logs.append(_NormLog("first_response_at", None, None, "FR_NOT_RECORDED"))
        return None

    def _resolved_at(self, st: SourceTicket, events: list[dict[str, Any]], logs: list[_NormLog]) -> datetime | None:
        resolved = [e["occurred_at"] for e in events if e["event_type"] == "resolved"]
        if resolved:  # SLA contract §3.3: the FINAL resolved event counts
            logs.append(_NormLog("resolved_at", None, resolved[-1].isoformat(), "RESOLVED_FINAL_EVENT"))
            return resolved[-1]  # type: ignore[no-any-return]
        if st.resolved_raw not in (None, ""):
            parsed = parse_timestamp(st.resolved_raw)
            logs.append(_NormLog("resolved_at", None, parsed.value.isoformat(), parsed.rule))
            return parsed.value
        return None

    def _store_pii(self, record: SourceRecord, redaction: RedactionResult, region: str | None) -> list[PiiDetection]:
        detections: list[PiiDetection] = []
        for d in redaction.detections:
            detections.append(
                PiiDetection(
                    source_record_id=record.id,
                    field=d.field,
                    entity_type=d.entity_type,
                    token=d.token,
                    start=d.start,
                    end=d.end,
                    method=d.method,
                    confidence=d.confidence,
                    checksum_valid=d.checksum_valid,
                )
            )
        self.session.add_all(detections)
        for token, (entity_type, value) in redaction.vault.items():
            self.session.add(
                PiiVaultEntry(
                    source_record_id=record.id,
                    token=token,
                    entity_type=entity_type,
                    region=region,
                    value_encrypted=vault.encrypt(value),
                    retention_until=self.retention_until,
                )
            )
        return detections

    def _store_logs(self, record: SourceRecord, ticket_id: uuid.UUID | None, logs: list[_NormLog]) -> None:
        for entry in logs:
            self.session.add(
                NormalizationLog(
                    source_record_id=record.id,
                    ticket_id=ticket_id,
                    field=entry.field,
                    original_value=entry.original[:200] if entry.original else None,
                    normalized_value=entry.normalized,
                    rule=entry.rule,
                )
            )


def _check_sources(source_dir: Path) -> str | None:
    for rel, _ in SOURCES:
        if not (source_dir / rel).is_file():
            raise SourceDataMissing(f"missing source file: {rel} (run scripts/source_data.py fetch)")
    manifest = source_dir.parent / "source_manifest.json"
    if not manifest.is_file():
        return None
    commit = json.loads(manifest.read_text(encoding="utf-8")).get("upstream_commit")
    return str(commit) if commit else None


async def run_ingestion(
    session: AsyncSession,
    source_dir: Path,
    *,
    triggered_by: uuid.UUID | None = None,
    retention_days: int = 365,
    now: datetime | None = None,
) -> IngestionBatch:
    commit = await asyncio.to_thread(_check_sources, source_dir)

    batch = IngestionBatch(triggered_by=triggered_by, source_commit=commit, status="running")
    session.add(batch)
    await session.flush()

    reference_counts = await load_reference(session, source_dir)
    await session.flush()
    run = IngestionRun(session, source_dir, now or datetime.now(tz=UTC), retention_days)
    await run.prepare()

    per_source: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: Counter[str] = Counter()
    pii_entities: Counter[str] = Counter()
    free_text_entities: Counter[str] = Counter()
    free_text_records: Counter[str] = Counter()
    for rel, parser in SOURCES:
        path = source_dir / rel
        file_sha = await asyncio.to_thread(sha256_file, path)
        counts = per_source[rel]
        document = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
        for st in parser(document):
            counts["read"] += 1
            previous_hash = run.existing_records.get((st.source_file, st.record_index))
            if previous_hash is not None:
                counts["skipped" if previous_hash == st.record_hash else "source_changed"] += 1
                continue
            try:
                async with session.begin_nested():
                    outcome = await run.process(st, batch.id, file_sha)
            except (TimestampError, ValueError, KeyError, TypeError) as exc:
                async with session.begin_nested():
                    session.add(
                        SourceRecord(
                            batch_id=batch.id,
                            source_file=st.source_file,
                            source_sha256=file_sha,
                            record_index=st.record_index,
                            record_hash=st.record_hash,
                            external_id=st.external_id,
                            channel=st.channel,
                            status="failed",
                            status_reasons=[type(exc).__name__, str(exc)[:200]],
                            raw_encrypted=vault.encrypt(json.dumps(st.raw, ensure_ascii=False)),
                        )
                    )
                counts["failed"] += 1
                log.warning("record failed", extra={"component": "ingestion", "error_type": type(exc).__name__})
                continue
            counts[outcome.status] += 1
            reasons.update(outcome.reasons)
            pii_entities.update(outcome.pii_entities)
            if outcome.free_text_pii and outcome.status != "duplicate":
                free_text_entities.update(outcome.free_text_pii)
                free_text_records[rel] += 1

    totals: Counter[str] = Counter()
    for c in per_source.values():
        totals.update(c)
    batch.summary = {
        "reference": reference_counts,
        "sources": {k: dict(v) for k, v in per_source.items()},
        "totals": dict(totals),
        "review_reasons": dict(reasons),
        "pii": {
            "all_entities_incl_contact_fields": dict(pii_entities),
            "records_with_pii_in_free_text": dict(free_text_records),
            "free_text_entities_excl_duplicates": dict(free_text_entities),
        },
    }
    batch.status = "failed" if totals.get("source_changed") else "completed"
    batch.finished_at = datetime.now(tz=UTC)
    await audit.record(
        session,
        "ingestion.completed",
        actor_user_id=triggered_by,
        entity_type="ingestion_batch",
        entity_id=str(batch.id),
        details={"totals": dict(totals)},
    )
    await session.commit()
    return batch
