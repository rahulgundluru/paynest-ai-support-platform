# Phase 4 – Human approval and security

## Review queue and approval workflow (`services/approvals/`, `/api/v1/approvals`)

Routing rules R1, R2, R5, R6 and R7 (instructions aimed at an AI, unverified customer, no category or low confidence, P1 pay/billing, statutory answers) open a **review item**. Each item holds:

- **Evidence pack:** a summary, customer and tier, SLA status and credit exposure, routing reason, incident links, knowledge **in force on the ticket date**, statutory values in force on that date, the PII tokens present, and any injection signals.
- **Draft:** redacted text with tokens only.
- **Validation report** for the current draft.
- **Full event history.**

The workflow state is in PostgreSQL, so a pending item survives restarts and resumes where it stopped.

| Action | Rule |
|---|---|
| `edit` (PUT draft) | Re-validates immediately and stores the report |
| `approve` | Only with a draft that passes **every** validation check. Never for `block` items. **Two-person rule** for R6/R7: the last editor can't approve. |
| `reject` / `escalate` (L2, L3, Security, DPO) / `reassign` (queue) / `resolve` (note required) | Only from `pending`; every action is audited |

The platform has **no capability to move money, approve refunds or change payroll data**, and drafts that promise these fail validation.

**Learned memory** is written only when a person approves a reply. Each entry is scoped to its customer and region, records the policy versions it cited, and expires when the earliest of those versions stops being in force. Unapproved AI output is never stored as memory.

**LangGraph decision:** the approval state machine is plain SQL tables. It already gives pause, resume and an audit trail, and needs no graph runtime. LangGraph's checkpointer becomes worthwhile once a multi-step drafting agent exists (model access, D7). The tables map onto its `interrupt()` and resume.

## Output validation, G6 (`services/validation/output.py`)

| Check | Catches |
|---|---|
| `no_raw_pii` / `tokens_belong_to_ticket` | Identifier patterns in the reply; tokens that don't belong to this ticket |
| `no_financial_commitment` | "refund … approved", "we have credited", "set your balance to …" |
| `no_injection_echo` | Instruction-like text, prompt disclosure, "admin mode" |
| `no_other_customer` | Another customer's name (tenant isolation) |
| `statutory_values_current` | A superseded value (e.g. INR 15,000 after 1 Aug; 14 columns after 15 Jul) or a value not yet in force |
| `citations_in_force` / `statutory_citation` | Cited KB or rule ids must be in force on the ticket date; statutory replies must cite one |
| `non_empty`, `no_abusive_language` | Basic quality |

**Result:** all 13 planted wrong drafts are caught, and the correct drafts pass (`tests/test_validation_ratelimit.py`).

## Security controls added

- **Login rate limiting:** 10 attempts per 5 minutes per (email, client); returns 429 with `Retry-After`; audited. The limiter runs in-process, so the limit applies per instance; a WAF rate rule provides the global limit in AWS (Phase 7).
- **PII reveal:**
  - **DPO only;** admins are deliberately excluded.
  - Each reveal is one token on one ticket, with a required reason of at least 10 characters.
  - The audit entry records the token, type and reason, never the value.
  - Values past their retention date return 410.
- **Region scoping** applies to approvals and memory.
- **Proxy fix:** the frontend proxy now forwards PUT. This was found during the browser check; backend tests call the API directly, so they couldn't catch it.

## Results (pinned source `502e718`)

| Check | Result |
|---|---|
| Review queue | 288 items (R1 1 · R2 64 · R5 109 · R6 28 · R7 86); idempotent rebuild |
| Statutory approval flow | A stale draft fails validation (422 on approve); the author can't approve (403, two-person rule); a second L2 approves; memory cites R-IN-PF-2026-08 v2 |
| PN-101129 | Can't be approved (409); escalated to Security |
| Memory | 0 entries from unapproved items |
| PII reveal | Admin 403; DPO gets the value; the audit log holds the reason without the value |

## Still open

- **Database row-level security:** needs a non-owner application role, which belongs with the AWS database setup in Phase 7. Region isolation is currently enforced in every query and covered by tests.
- **AI-drafted replies and the semantic cache:** need model access (D7). The review UI states plainly that no drafting model is configured.
- **Message delivery:** "Approve reply" records the approved reply. No channel integration (email or WhatsApp) exists in the pilot, so nothing is sent externally.
