"""Source-specific adapters. Each turns one raw record into a channel-neutral `SourceTicket`.

Adapters only RESHAPE; they do not normalize values, redact, or touch the database. Free text is
still raw here, so a SourceTicket must go straight into the PII gate and never be logged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

EXPORT_FILE = "data-room/data/tickets_export.json"
WHATSAPP_FILE = "data-room/data/whatsapp_export.json"
CALLS_FILE = "data-room/data/call_center_notes.json"


class AdapterError(ValueError):
    pass


@dataclass
class RawEvent:
    event_type: str
    time_raw: Any
    actor: str | None
    data: dict[str, Any]


@dataclass
class RawMessage:
    author_type: str  # customer | agent | system
    sent_raw: Any
    text: str


@dataclass
class SourceTicket:
    channel: str
    source_file: str
    record_index: int
    raw: Any
    external_id: str | None
    customer_id: str | None = None
    customer_name_hint: str | None = None
    partner_id: str | None = None
    subject: str | None = None
    body: str | None = None
    contact_fields: dict[str, str | None] = field(default_factory=dict)  # structured PII (email, phone)
    messages: list[RawMessage] = field(default_factory=list)
    events: list[RawEvent] = field(default_factory=list)
    priority_raw: str | None = None
    final_category_raw: str | None = None
    status_raw: str | None = None
    created_raw: Any = None
    first_response_raw: Any = None
    resolved_raw: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def record_hash(self) -> str:
        canonical = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _events(rows: list[dict[str, Any]], type_key: str, time_key: str, actor_key: str, data_key: str) -> list[RawEvent]:
    return [
        RawEvent(str(r[type_key]).lower(), r.get(time_key), r.get(actor_key), dict(r.get(data_key) or {})) for r in rows
    ]


def _email(t: dict[str, Any], index: int) -> SourceTicket:
    return SourceTicket(
        channel="email",
        source_file=EXPORT_FILE,
        record_index=index,
        raw=t,
        external_id=t["ticket_id"],
        customer_id=t.get("customer_id"),
        subject=t.get("subject"),
        body=t.get("body"),
        contact_fields={"from_email": t.get("from_email")},
        events=_events(t.get("events") or [], "event", "ts", "actor", "meta"),
        priority_raw=t.get("priority"),
        final_category_raw=t.get("category"),
        status_raw=t.get("status"),
        created_raw=t.get("received_at"),
        first_response_raw=t.get("first_response_at"),
        resolved_raw=t.get("resolved_at"),
        attributes={"assigned_group": t.get("assigned_group")},
    )


def _widget(t: dict[str, Any], index: int) -> SourceTicket:
    return SourceTicket(
        channel="widget",
        source_file=EXPORT_FILE,
        record_index=index,
        raw=t,
        external_id=t["tkt"],
        customer_id=t.get("org_id"),
        subject=t.get("title"),
        body=t.get("message"),
        events=_events(t.get("history") or [], "action", "time", "who", "data"),
        priority_raw=t.get("prio"),
        final_category_raw=t.get("cat"),
        status_raw=t.get("state"),
        created_raw=t.get("created"),
        first_response_raw=t.get("first_reply_ts"),
        resolved_raw=t.get("closed_ts"),
        attributes={"user_ref": t.get("user_ref")},
    )


def _partner(t: dict[str, Any], index: int) -> SourceTicket:
    return SourceTicket(
        channel="partner_portal",
        source_file=EXPORT_FILE,
        record_index=index,
        raw=t,
        external_id=t["reference"],
        customer_id=t.get("tenant"),
        customer_name_hint=t.get("end_customer"),
        partner_id=t.get("partner_id"),
        subject=t.get("summary"),
        body=t.get("details"),
        events=_events(t.get("activity_log") or [], "evt", "when", "user", "info"),
        priority_raw=t.get("severity"),
        final_category_raw=t.get("topic"),
        status_raw=t.get("status"),
        created_raw=t.get("opened_on"),
        first_response_raw=t.get("fr_at"),
        resolved_raw=t.get("closed_at"),
    )


def parse_export(document: dict[str, Any]) -> Iterator[SourceTicket]:
    """tickets_export.json: three per-channel schemas mixed in one list, told apart by their id key."""
    for index, t in enumerate(document.get("tickets") or []):
        if "ticket_id" in t:
            yield _email(t, index)
        elif "tkt" in t:
            yield _widget(t, index)
        elif "reference" in t:
            yield _partner(t, index)
        else:
            raise AdapterError(f"record {index}: unrecognised ticket schema (keys: {sorted(t)[:6]})")


def parse_whatsapp(threads: list[dict[str, Any]]) -> Iterator[SourceTicket]:
    for index, w in enumerate(threads):
        messages = [
            RawMessage("customer" if m.get("from") == "customer" else "agent", m.get("ts"), m.get("text") or "")
            for m in w.get("messages") or []
        ]
        first_customer = next((m for m in messages if m.author_type == "customer"), None)
        first_agent = next((m for m in messages if m.author_type == "agent"), None)
        yield SourceTicket(
            channel="whatsapp",
            source_file=WHATSAPP_FILE,
            record_index=index,
            raw=w,
            external_id=w.get("ticket_id"),
            customer_name_hint=w.get("customer_hint"),
            body=first_customer.text if first_customer else None,
            contact_fields={"wa_contact": w.get("wa_contact")},
            messages=messages,
            status_raw="closed" if w.get("closed") else "open",
            created_raw=(first_customer or messages[0]).sent_raw if messages else None,
            first_response_raw=first_agent.sent_raw if first_agent else None,
            attributes={"thread_id": w.get("thread_id"), "message_count": len(messages)},
        )


def parse_calls(calls: list[dict[str, Any]]) -> Iterator[SourceTicket]:
    for index, c in enumerate(calls):
        yield SourceTicket(
            channel="phone",
            source_file=CALLS_FILE,
            record_index=index,
            raw=c,
            external_id=c.get("ticket_id"),
            customer_id=c.get("customer_id"),
            body=c.get("summary"),  # the agent's call note is the only text a phone ticket has
            created_raw=c.get("called_at"),
            attributes={
                "call_id": c.get("call_id"),
                "agent_id": c.get("agent_id"),
                "duration_min": c.get("duration_min"),
                "disposition": c.get("disposition"),
                "callback_required": c.get("callback_required"),
            },
        )
