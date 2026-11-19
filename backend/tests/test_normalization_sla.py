from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.customer_lookup import region_from_phone
from app.services.normalization import rules
from app.services.normalization.timestamps import IST, TimestampError, in_payroll_window, parse_timestamp
from app.services.sla.engine import SlaTerms, evaluate

ENT_P1 = SlaTerms("v3.2", Decimal(1), Decimal(8), Decimal(10))
ENT_P3 = SlaTerms("v3.2", Decimal(8), Decimal(72), Decimal(2))
T0 = datetime(2026, 8, 25, 10, 0, tzinfo=IST)


@pytest.mark.parametrize(
    ("channel", "raw", "expected"),
    [
        ("email", "P1", "P1"),
        ("widget", "urgent", "P1"),
        ("widget", "high", "P2"),
        ("widget", "normal", "P3"),
        ("partner_portal", "S1", "P1"),
        ("partner_portal", "S3", "P3"),
        ("widget", "P1", None),  # wrong vocabulary for the channel is not guessed
    ],
)
def test_priority_mapping(channel, raw, expected):
    assert rules.map_priority(channel, raw).value == expected


def test_category_mapping_covers_known_spellings_and_refuses_unknown():
    assert rules.map_category("Compliance - PF/WPS").value == "statutory"
    assert rules.map_category("  PAYROLL   ISSUE ").value == "payroll"
    assert rules.map_category("New Customer Setup").value == "onboarding"
    unknown = rules.map_category("Something else")
    assert unknown.value is None and unknown.rule == "CATEGORY_UNKNOWN_LABEL"
    assert set(rules.CATEGORY_LABELS.values()) == set(rules.CATEGORY_QUEUE)  # all nine categories reachable


@pytest.mark.parametrize(
    ("raw", "expected_utc", "rule"),
    [
        ("2026-08-10T09:36:23+05:30", "2026-08-10T04:06:23+00:00", "TS_ISO_OFFSET"),
        ("2026-08-10T04:06:23Z", "2026-08-10T04:06:23+00:00", "TS_ISO_UTC_Z"),
        ("2026-08-10 09:36:23", "2026-08-10T04:06:23+00:00", "TS_NAIVE_ASSUMED_IST"),
        (1787638131000, "2026-08-25T06:08:51+00:00", "TS_EPOCH_MS_UTC"),
        ("01/08/2026 13:05 GST", "2026-08-01T09:05:00+00:00", "TS_LABELLED_GST"),
        ("01/08/2026 14:35 IST", "2026-08-01T09:05:00+00:00", "TS_LABELLED_IST"),
        ("01-07-2026 17:19", "2026-07-01T11:49:00+00:00", "TS_CALL_NAIVE_ASSUMED_IST_UNVERIFIED"),
    ],
)
def test_timestamp_formats(raw, expected_utc, rule):
    parsed = parse_timestamp(raw)
    assert parsed.value.astimezone(UTC).isoformat() == expected_utc
    assert parsed.rule == rule


def test_bad_timestamp_raises_without_echoing_value():
    with pytest.raises(TimestampError) as exc:
        parse_timestamp("yesterday 25:99")
    assert "25" not in str(exc.value)


def test_payroll_window_uses_25th_to_3rd():
    assert in_payroll_window(datetime(2026, 8, 25, 0, 5, tzinfo=IST))
    assert in_payroll_window(datetime(2026, 9, 3, 23, 0, tzinfo=IST))
    assert not in_payroll_window(datetime(2026, 9, 4, 0, 0, tzinfo=IST))


def test_region_from_phone_never_implies_customer():
    assert region_from_phone("+971 00000 04115") == "UAE"
    assert region_from_phone("+91 00000 08603") == "IN"
    assert region_from_phone(None) is None


def _eval(**kw):
    base = dict(
        tier="Enterprise",
        priority="P1",
        created_at=T0,
        first_response_at=T0 + timedelta(minutes=30),
        resolved_at=T0 + timedelta(hours=6),
        monthly_fee_usd=Decimal("4200"),
        terms=ENT_P1,
        as_of=T0 + timedelta(days=30),
    )
    base.update(kw)
    return evaluate(**base)


def test_within_target_has_no_credit():
    r = _eval()
    assert r.resolution_breached is False and r.credit_usd is None and r.first_response_breached is False


def test_breach_uses_base_percentage():
    r = _eval(resolved_at=T0 + timedelta(hours=12))
    assert r.resolution_breached and r.severity_multiplier == Decimal("1.0")
    assert r.credit_pct == Decimal(10) and r.credit_usd == Decimal("420.00")


def test_more_than_twice_target_applies_multiplier():
    r = _eval(resolved_at=T0 + timedelta(hours=16, minutes=1))
    assert r.severity_multiplier == Decimal("1.5") and r.credit_usd == Decimal("630.00")
    exactly_twice = _eval(resolved_at=T0 + timedelta(hours=16))
    assert exactly_twice.severity_multiplier == Decimal("1.0")  # "exceeds twice" is strict


def test_enterprise_p3_matches_finance_row_br_0001():
    # sla_breaches_q3.csv BR-0001: Enterprise P3, 179.8 h vs 72 h, fee 3370 -> 3.0 %, USD 101.10
    r = _eval(priority="P3", terms=ENT_P3, monthly_fee_usd=Decimal("3370"), resolved_at=T0 + timedelta(hours=179.8))
    assert r.credit_pct == Decimal("3.0") and r.credit_usd == Decimal("101.10")


def test_open_ticket_reports_remaining_time_but_no_credit():
    r = _eval(first_response_at=None, resolved_at=None, as_of=T0 + timedelta(hours=2))
    assert r.first_response_breached is True
    assert r.resolution_breached is False and r.resolution_remaining_hours == Decimal("6.00")
    assert r.credit_usd is None


def test_standard_and_unknown_customers_are_not_applicable():
    assert _eval(tier="Standard").not_applicable_reason == "standard_tier_best_effort"
    assert _eval(tier=None).not_applicable_reason == "customer_unresolved"
    assert _eval(priority=None).not_applicable_reason == "priority_missing"
