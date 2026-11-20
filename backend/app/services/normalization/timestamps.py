"""Timestamp parsing for every format found in the source systems. All results are timezone-aware.

Rule ids are written to normalization_log so each converted timestamp says how it was interpreted.
TS_NAIVE_ASSUMED_IST is assumption A1: the client believes naive values are IST; profiling confirmed
it for email/widget/partner (naive wall-clock equals the +05:30 event times). For phone notes the
assumption could not be checked, so they use a separate, explicitly unverified rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
GST = timezone(timedelta(hours=4), "GST")
_LABELLED = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2}) (IST|GST)$")
_CALL = re.compile(r"^(\d{2})-(\d{2})-(\d{4}) (\d{2}):(\d{2})$")


class TimestampError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedTime:
    value: datetime
    rule: str


def parse_timestamp(raw: object, *, naive_rule: str = "TS_NAIVE_ASSUMED_IST") -> ParsedTime:
    if raw is None or raw == "":
        raise TimestampError("empty timestamp")
    if isinstance(raw, bool):
        raise TimestampError("boolean is not a timestamp")
    if isinstance(raw, int | float):
        return ParsedTime(datetime.fromtimestamp(raw / 1000, tz=UTC), "TS_EPOCH_MS_UTC")
    text = str(raw).strip()
    if m := _LABELLED.match(text):
        day, month, year, hour, minute, zone = m.groups()
        tz = IST if zone == "IST" else GST
        return ParsedTime(
            datetime(int(year), int(month), int(day), int(hour), int(minute), tzinfo=tz), f"TS_LABELLED_{zone}"
        )
    if m := _CALL.match(text):
        day, month, year, hour, minute = m.groups()
        return ParsedTime(
            datetime(int(year), int(month), int(day), int(hour), int(minute), tzinfo=IST),
            "TS_CALL_NAIVE_ASSUMED_IST_UNVERIFIED",
        )
    try:
        if text.endswith("Z"):
            return ParsedTime(datetime.fromisoformat(text[:-1] + "+00:00"), "TS_ISO_UTC_Z")
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError as exc:
        raise TimestampError(f"unrecognised timestamp format: {re.sub(r'[0-9]', '9', text)[:40]}") from exc
    if parsed.tzinfo is None:
        return ParsedTime(parsed.replace(tzinfo=IST), naive_rule)
    return ParsedTime(parsed, "TS_ISO_OFFSET")


def in_payroll_window(moment: datetime) -> bool:
    """Payroll week = 25th to 3rd (payroll_week_runbook.md), evaluated on the IST calendar date."""
    day = moment.astimezone(IST).day
    return day >= 25 or day <= 3
