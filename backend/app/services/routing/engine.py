"""Deterministic routing engine. The LLM never decides the route; it only supplies typed inputs.

Rules are evaluated in order; the first match wins. Same inputs + same RULESET_VERSION => same decision.
Lanes (Session 2 design): auto_answer, draft_for_agent, route_queue, incident, human_review, block.
`auto_answer` is gated by configuration and is OFF in the pilot: How-To drafts still go to an agent
until two weeks of shadow-mode evidence exist (Session 4 §4.5).

Evidence for each rule:
  R1 injection           PN-101129; DPO 07 [00:06:38]; no ticket text may drive an action
  R2 unknown customer    no tier/SLA/region => cannot route or answer safely (65 partner, 57 WA tickets)
  R3 resubmission        follow-ups go to the original case's owner (one client, one case)
  R4 incident            runbook §9 / escalation policy: one incident, L2 owns it, engineering paged
  R5 low confidence      classifier output below threshold => a human decides
  R6 money / payroll P1  runbook + DPO + CFO: humans approve anything touching pay or credits
  R7 statutory           answers must cite the rule in force on the ticket date; human sends
  R8 how-to              cheapest lane; auto-answer only when enabled
  R9 default             category queue from the triage SOP
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from app.services.normalization.rules import CATEGORY_QUEUE

RULESET_VERSION = "route-2026.11.19"

QUEUE_LEVEL = {
    "General-L1": "L1",
    "Access-Support": "L1",
    "Onboarding": "L1",
    "Billing": "L1",
    "Reports-Analytics": "L1",
    "Leave-Attendance": "L1",
    "Payroll-Ops": "L2",
    "Statutory-Compliance": "L2",
    "Integrations": "L2",
    "Incident-Response": "L2",
    "Engineering-L3": "L3",
    "Human-Review": "HUMAN_REVIEW",
    "Security-Review": "HUMAN_REVIEW",
    "Customer-Verification": "HUMAN_REVIEW",
}


@dataclass(frozen=True)
class RoutingInput:
    category: str | None
    category_source: str  # classifier | customer_pick | none
    priority: str | None
    tier: str | None
    region: str | None
    customer_resolved: bool
    is_injection: bool = False
    classifier_confidence: float | None = None
    requires_human: bool = False
    incident_queue: str | None = None  # set when the ticket belongs to an open incident
    resubmission_of_queue: str | None = None  # set when it is a follow-up of an earlier ticket
    in_payroll_window: bool = False


@dataclass(frozen=True)
class RoutingConfig:
    confidence_threshold: float = 0.80
    auto_answer_enabled: bool = False


@dataclass(frozen=True)
class Decision:
    lane: str
    queue: str
    support_level: str
    rule_id: str
    reason: str
    requires_approval: bool
    rule_version: str = RULESET_VERSION

    @staticmethod
    def make(lane: str, queue: str, rule_id: str, reason: str, requires_approval: bool) -> Decision:
        return Decision(lane, queue, QUEUE_LEVEL.get(queue, "L1"), rule_id, reason, requires_approval)


def inputs_hash(inp: RoutingInput, config: RoutingConfig) -> str:
    payload = {"input": asdict(inp), "config": asdict(config), "ruleset": RULESET_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def route(inp: RoutingInput, config: RoutingConfig = RoutingConfig()) -> Decision:
    if inp.is_injection:
        return Decision.make(
            "block", "Security-Review", "R1",
            "Instructions aimed at the assistant were detected in customer text; no automated action is taken.",
            True,
        )  # fmt: skip
    if not inp.customer_resolved:
        return Decision.make(
            "human_review", "Customer-Verification", "R2",
            "Customer identity is not verified, so tier, SLA and region-specific answers are unknown.",
            True,
        )  # fmt: skip
    if inp.resubmission_of_queue:
        return Decision.make(
            "route_queue", inp.resubmission_of_queue, "R3",
            "Follow-up of an earlier ticket: routed to the original case's queue and linked to it.",
            False,
        )  # fmt: skip
    if inp.incident_queue:
        return Decision.make(
            "incident", inp.incident_queue, "R4",
            "Part of an open multi-ticket incident for this customer; handled as one case.",
            False,
        )  # fmt: skip
    if inp.category is None or (
        inp.category_source == "classifier"
        and (inp.requires_human or (inp.classifier_confidence or 0.0) < config.confidence_threshold)
    ):
        return Decision.make(
            "human_review", "Human-Review", "R5",
            "No category, or classifier confidence below threshold / classifier asked for a human.",
            True,
        )  # fmt: skip
    queue = CATEGORY_QUEUE[inp.category]
    if inp.category in ("payroll", "billing") and inp.priority == "P1":
        return Decision.make(
            "draft_for_agent", queue, "R6",
            "P1 on pay or billing: the AI may draft, a person must approve before anything is sent.",
            True,
        )  # fmt: skip
    if inp.category == "statutory":
        return Decision.make(
            "draft_for_agent", queue, "R7",
            "Statutory question: the draft must cite the rule in force on the ticket date; a person sends it.",
            True,
        )  # fmt: skip
    if inp.category == "how_to":
        if config.auto_answer_enabled and inp.priority == "P3":
            return Decision.make("auto_answer", queue, "R8", "How-To with a cited, cacheable answer.", False)
        return Decision.make(
            "draft_for_agent", queue, "R8",
            "How-To: AI drafts from cited knowledge; auto-answer is disabled in the pilot.",
            False,
        )  # fmt: skip
    return Decision.make("route_queue", queue, "R9", f"Category '{inp.category}' routes to {queue}.", False)
