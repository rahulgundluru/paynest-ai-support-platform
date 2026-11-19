# Phase 3 – AI pipeline

```
redacted ticket ─► injection screen (rules) ─► classifier (model, typed) ─► duplicate / incident ─► routing (rules)
                                                   │  no model configured?                       │
                                                   └► status "unavailable" → a person decides     └► decision + rule id + inputs hash
question + ticket date ─► PII-redact ─► SQL filters (region, approved, effective window) ─► rank (full-text) ─► cited chunks
```

## Knowledge base (`services/knowledge/`)

| Source | Documents | Versions and validity |
|---|---|---|
| `statutory_rules.json` | 4 rules | Two versions each: the old value valid until the day before `effective_from`, the new value valid from it |
| `kb_articles.json` | 24 articles | Bodies aren't in the source; only 4 have a one-line excerpt, so 20 are indexed **title only** (`content_complete = false`) |
| `process/*.md` | 4 documents (triage SOP, escalation policy, payroll-week runbook, SLA Schedule 3) | Chunked by heading. The SLA schedule is valid from 2025-01-01 (stated in its header). |

**Derived validity.** An article affected by a rule (via `affects_kb_topics`) whose `last_reviewed` date is *before* that rule's effective date can't describe the new rule. Its validity therefore ends the day before the rule's effective date, and `validity_source` records `derived:<rule_id>`:

| Article | Valid until | Because of |
|---|---|---|
| KB-0142, KB-0143 | 2026-07-31 | R-IN-PF-2026-08 |
| KB-0201, KB-0202 | 2026-07-14 | R-UAE-WPS-2026-07 |

`last_reviewed` is never used as an effective date. KB-0150 (TDS) was reviewed after its rule took effect, so it stays valid.

**Retrieval** (`retrieval.py`):
- Filters in SQL first: region (the ticket's region plus ALL), approved versions only, `effective_from <= as_of <= effective_to`. Ranking comes after.
- Ranks with PostgreSQL full-text search (`simple` config) and boosts exact ids (KB-0202, R-UAE-WPS-2026-07).
- Every search is logged (`retrieval_logs` / `retrieval_results`).
- The query is PII-redacted before it is searched or logged.

**Statutory rates** (`GET /statutory/rates?region&as_of`) mirror the payroll engine's endpoint for the four source rules.

## Duplicates and incidents (`services/deduplication/`)

| Rule | Logic | Evidence |
|---|---|---|
| D1 | The ticket cites an earlier ticket id from the same customer | 18 of the 26 known resubmissions |
| D2 | A follow-up marker ("RE:", "Second request", "Following up") plus the same normalized subject from the same customer within 7 days. If several originals match, confidence drops to 0.6 and a person confirms. | 8 of the 26 |
| — | Similar text alone **never** merges tickets | 199 same-customer, same-text pairs that are *not* duplicates |
| I1 | 5 or more tickets from one customer in one category, each within 3 h of the previous, become one incident, declared at the 5th ticket | Runbook §9; the Meridian burst |

Tickets are grouped into a case, not merged: each keeps its channel, messages and history. Manual link and unlink actions are permissioned, audited, and preserved when detection re-runs. Linking another customer's ticket is refused.

## Routing (`services/routing/engine.py`, ruleset `route-2026.11.19`)

| Rule | When | Outcome |
|---|---|---|
| R1 | Instructions aimed at an AI | `block` → Security-Review |
| R2 | Customer not verified | `human_review` → Customer-Verification |
| R3 | Resubmission | Routed to the original case's queue |
| R4 | Open incident | `incident` → Incident-Response |
| R5 | No category, low confidence, or the classifier asks for a human | `human_review` |
| R6 | Payroll or billing at P1 | Drafted, with approval required |
| R7 | Statutory | Drafted with a dated citation |
| R8 | How-To | Drafted (auto-answer is off in the pilot) |
| R9 | Anything else | The category's queue |

Every decision is stored with its rule id, ruleset version, reason, input snapshot and input hash, so the same inputs always give the same decision.

## Classifier (`services/classification/`, `ai/`)

- **Provider-neutral:** `LLMProvider` / `EmbeddingProvider` interfaces, with an AWS Bedrock adapter (Converse API with a forced tool call for typed output). Model ids and region come from configuration. **No model ids are hard-coded,** because in-region availability for India and the UAE must be confirmed first.
- **Prompt:** `classify-v1`. Ticket text is wrapped as untrusted data. Business rules live in code, not in the prompt.
- **Inputs:** redacted text and the customer's original pick only. The export's final label (the answer key) is never sent.
- **Output checks:** Pydantic validation, one retry, then `invalid` → a person decides. Confidence below `CLASSIFICATION_CONFIDENCE_THRESHOLD` (0.80) → a person decides.
- **Network boundary:** `assert_no_pii` blocks any payload that still matches a PII pattern. This is the second, independent G1 check.
- **Injection screen:** a rule-based check runs whether or not a model is available. PN-101129 is blocked today with no model.
- **Usage tracking:** every call records tokens, latency and success in `model_usage`. Cost is estimated only when prices are configured.

## Results on the source data (pinned `502e718`)

| Check | Result |
|---|---|
| G5, PF ceiling by question date | June → INR 15,000 (KB-0142 and the rule's v1); September → INR 25,000 (rule v2), with KB-0142/0143 excluded |
| G5, the 48 tickets answered from stale articles | **0** stale chunks retrieved when each is replayed on its own date |
| WPS, 29 Jul question that names KB-0202 | KB-0202 excluded; the SIF v3 rule ranks first |
| G3, resubmissions | 25 of 26 correct (precision and recall 96%). The miss (PN-101510) had two possible originals and was flagged ambiguous (confidence 0.6). |
| G3, Meridian incident | Exactly 30 tickets, declared at the 5th ticket, 15 min after the first. Source data: about 6.6 h until escalation (per Slack) and 19.7 h until the Jira ticket. |
| Other incident flagged | Kestrel, 5 integration tickets on 10 Sep, consistent with the known sync bug PNJ-4412 |
| G4, PN-101129 | Rule R1 → `block`, through the rule-based screen with no model |
| Routing baseline (today's practice) | The customer's own pick reaches the correct final queue for 84.5% of tickets in the category lanes (1,092 / 1,293). This is the bar G2 must beat. |

## Pending: needs model access (decision D7)

- **G2 classification accuracy.** It can't be measured until a Bedrock model is configured and the routing labels for the 201 tickets that changed queue are reviewed (D3).
- **Embeddings and hybrid search.** The pgvector column and provider exist but are unused; retrieval is full-text only. Hindi and Arabic questions therefore match poorly until embeddings exist.
- **Answer generation (RAG drafts) with citations, and output validation.** Planned for Phase 4, on top of this retrieval.
- **Known-bug linking** (a new ticket matched to an open Jira issue for the same customer) is not built yet.
