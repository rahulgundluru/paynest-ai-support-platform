"""Deterministic output validation for every reply draft, whether written by the AI or by a person.

A draft can only be approved when every check passes. Checks (G6):
  non_empty                 draft present and bounded
  no_raw_pii                no identifier pattern in the text (tokens like <IBAN_1> only)
  tokens_belong_to_ticket   every PII token refers to this ticket's own redacted data
  no_financial_commitment   the system never promises refunds, credits, waivers or payments
  no_injection_echo         no instruction-like text or prompt disclosure
  no_other_customer         no other customer's name (tenant isolation, May payslip incident)
  statutory_values_current  no superseded (or not-yet-effective) statutory value for the ticket date
  citations_in_force        cited KB/rule ids exist and are in force on the ticket date
  statutory_citation        statutory answers must cite the rule/article in force
  no_abusive_language       basic wording check
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.services.classification.service import injection_signals
from app.services.pii.gate import contains_pii

VALIDATOR_VERSION = "validate-2026.11.19"
MAX_LENGTH = 5000

_TOKEN = re.compile(r"<([A-Z_]+_\d+)>")
_CITATION = re.compile(r"\b(KB-\d{4}|R-[A-Z]{2,3}-[A-Z]+-\d{4}-\d{2})\b")
_FINANCIAL = re.compile(
    r"\b(refund|credit|reimburse(?:ment)?|compensation|waive(?:d|r)?|payout)\b[^.]{0,60}?"
    r"\b(approved|processed|issued|granted|initiated|confirmed|will be (?:paid|credited|issued|processed))\b"
    r"|\b(we|i) (?:have |will |shall )?(approved|credited|refunded|waived|paid)\b"
    r"|\bset (?:your |the )?(?:invoice )?balance to\b",
    re.IGNORECASE,
)
_PROMPT_DISCLOSURE = re.compile(r"\b(system prompt|my instructions|admin mode)\b", re.IGNORECASE)
_ABUSIVE = re.compile(r"\b(idiot|stupid|shut up|useless customer|damn you)\b", re.IGNORECASE)
_AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b")
_COLUMNS = re.compile(r"\b(\d+)[\s-]*columns?\b", re.IGNORECASE)
_SIF = re.compile(r"\bsif\s*v(\d)\b", re.IGNORECASE)
_FY = re.compile(r"\bfy\s?(\d{2}-\d{2})\b", re.IGNORECASE)
_LEGAL_SUFFIX = re.compile(r"\s+(pvt ltd|ltd|llc|fze|fzco|trust)$", re.IGNORECASE)
_OLD_WORDS = re.compile(r"\b(old|older|previous|earlier|outdated|superseded|no longer|former)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RuleFacts:
    rule_id: str
    region: str
    effective_from: date
    old_value: str
    new_value: str


@dataclass(frozen=True)
class DocValidity:
    effective_from: date | None
    effective_to: date | None


@dataclass
class ValidationContext:
    ticket_date: date
    region: str | None
    category: str | None
    customer_name: str | None
    other_customer_names: list[str]
    ticket_tokens: set[str]
    rules: list[RuleFacts]
    documents: dict[str, list[DocValidity]]  # document id -> versions' windows
    statutory_answer: bool = False
    superseded_by: dict[str, str] = field(default_factory=dict)  # stale doc id -> rule id


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class ValidationReport:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    validator_version: str = VALIDATOR_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "validator_version": self.validator_version,
            "checks": [asdict(c) for c in self.checks],
        }


def _markers(value: str) -> set[str]:
    found = {re.sub(r"[,\s]", "", m) for m in _AMOUNT.findall(value)}
    found |= {f"{n} columns" for n in _COLUMNS.findall(value)}
    found |= {f"sif v{n}" for n in _SIF.findall(value)}
    found |= {f"fy{n}" for n in _FY.findall(value)}
    return found


def _draft_markers(text: str) -> set[str]:
    return _markers(text)


def _valid_on(windows: list[DocValidity], day: date) -> bool:
    return any(
        (w.effective_from is None or w.effective_from <= day) and (w.effective_to is None or w.effective_to >= day)
        for w in windows
    )


def _short_name(name: str) -> str:
    return _LEGAL_SUFFIX.sub("", name.strip())


def validate_draft(text: str | None, ctx: ValidationContext) -> ValidationReport:
    checks: list[Check] = []
    body = text or ""

    checks.append(Check("non_empty", 0 < len(body.strip()) <= MAX_LENGTH, f"{len(body)} characters"))
    checks.append(
        Check("no_raw_pii", not contains_pii(body), "identifier pattern found" if contains_pii(body) else "ok")
    )
    unknown = sorted({t for t in _TOKEN.findall(body)} - ctx.ticket_tokens)
    checks.append(Check("tokens_belong_to_ticket", not unknown, f"unknown tokens: {unknown}" if unknown else "ok"))

    money = _FINANCIAL.search(body)
    checks.append(
        Check(
            "no_financial_commitment",
            money is None,
            f"commitment wording: '{money.group(0)[:60]}'" if money else "ok",
        )
    )
    injection = injection_signals(body)
    disclosure = _PROMPT_DISCLOSURE.search(body)
    checks.append(
        Check(
            "no_injection_echo",
            not injection and disclosure is None,
            f"instruction-like text: {(injection or [disclosure.group(0) if disclosure else ''])[0][:60]}"
            if injection or disclosure
            else "ok",
        )
    )

    lowered = body.casefold()
    leaked = sorted(
        {
            name
            for name in ctx.other_customer_names
            if name and name != ctx.customer_name and len(_short_name(name).split()) >= 2
            and _short_name(name).casefold() in lowered
        }
    )  # fmt: skip
    checks.append(Check("no_other_customer", not leaked, f"mentions: {leaked}" if leaked else "ok"))

    draft_marks = _draft_markers(body)
    problems: list[str] = []
    for rule in ctx.rules:
        if ctx.region and rule.region != ctx.region:
            continue
        old, new = _markers(rule.old_value), _markers(rule.new_value)
        old_only, new_only = old - new, new - old
        if not old_only and not new_only:
            continue
        uses_old, uses_new = bool(draft_marks & old_only), bool(draft_marks & new_only)
        if ctx.ticket_date >= rule.effective_from and uses_old and not uses_new:
            problems.append(f"{rule.rule_id}: states the value superseded on {rule.effective_from.isoformat()}")
        if ctx.ticket_date < rule.effective_from and uses_new and not uses_old:
            problems.append(f"{rule.rule_id}: states a value not in force until {rule.effective_from.isoformat()}")
    checks.append(Check("statutory_values_current", not problems, "; ".join(problems) or "ok"))

    cited = sorted(set(_CITATION.findall(body)))

    def explained_as_superseded(doc_id: str) -> bool:
        # Citing an outdated article is allowed only to say it is outdated, next to the rule now in force.
        rule = ctx.superseded_by.get(doc_id)
        if not rule or rule not in cited or not _valid_on(ctx.documents.get(rule, []), ctx.ticket_date):
            return False
        return any(
            _OLD_WORDS.search(body[max(0, m.start() - 60) : m.end() + 60]) for m in re.finditer(re.escape(doc_id), body)
        )

    stale = [
        c
        for c in cited
        if (c not in ctx.documents or not _valid_on(ctx.documents[c], ctx.ticket_date))
        and not explained_as_superseded(c)
    ]
    checks.append(
        Check("citations_in_force", not stale, f"not in force on {ctx.ticket_date}: {stale}" if stale else "ok")
    )
    if ctx.statutory_answer:
        in_force = [c for c in cited if c in ctx.documents and _valid_on(ctx.documents[c], ctx.ticket_date)]
        checks.append(
            Check(
                "statutory_citation",
                bool(in_force),
                "cites " + ", ".join(in_force)
                if in_force
                else "a statutory answer must cite the rule or article in force",
            )
        )
    abusive = _ABUSIVE.search(body)
    checks.append(Check("no_abusive_language", abusive is None, "abusive wording" if abusive else "ok"))
    return ValidationReport(passed=all(c.passed for c in checks), checks=checks)
