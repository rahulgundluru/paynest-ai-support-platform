# Demo script

About 20 minutes. It follows the master specification's acceptance criteria: one real ticket through
the whole pipeline, including a sensitive scenario, a duplicate/incident scenario and a date-aware
retrieval scenario, followed by the measured evaluation results.

Every value quoted below was read from the running system on the pinned source data (`502e718`) on
20 Nov 2026. Steps 1–6 and 8–10 were checked against the live API and screens; the approval in
step 7 changes data, so it was not performed on the demo database: the same sequence runs in
`tests/test_phase4_acceptance.py` on an equivalent statutory ticket.

## Before the demo

1. Build the pipeline state and users as in the [deployment guide](../deployment/README.md#3-local-run-without-docker-verified).
   You need: an admin, a DPO, an `agent_l1`, and **two** users who can decide approvals.
2. Open http://localhost:3000 and sign in as the admin.
3. Approvals and reveals are permanent and audited. Rehearse on a copy of the database.
4. The source data names the upstream client in some ticket text. Present the product as PayNest (D1)
   and don't read those passages aloud.

## The story ticket: PN-101414

A partner-portal ticket from **Navrang Infotech Ltd** (C-1012, Enterprise, India), sent on
**28 Sep 2026, 17:43 IST**, during the payroll window: their accountant's PF figures differ from PayNest's,
and the customer pasted an Aadhaar number and a PAN into the message.

What happened in the source data: an L1 agent answered with **KB-0142**, an article that still says the
PF ceiling is INR 15,000 although the ceiling rose to INR 25,000 on 1 Aug 2026. The customer reopened
the ticket ("answer did not help"), an L2 agent confirmed the article was outdated, and the ticket was
resolved after 222.71 hours against a 72-hour target, a **USD 88.50** SLA credit.

This one ticket shows three of the five business problems: stale knowledge, PII exposure and an SLA
breach.

## 1. Ingestion and PII (Tickets → PN-101414), 3 min

Open **Tickets**, search `PN-101414`, open it.

- **Message (redacted):** the Aadhaar and PAN appear as `<AADHAAR_1>` and `<PAN_1>`. The originals were
  encrypted into the vault at ingestion; this screen cannot show them.
- **PII detections:** both found by format (`regex`), both with *checksum failed*. The case data is synthetic,
  and a failed checksum never un-redacts a value.
- **Normalization and provenance:** source `tickets_export.json` record #654; partner priority `S3` → `P3`
  (`PRIORITY_PARTNER_PORTAL_MAP`); naive timestamps read as IST (`TS_NAIVE_ASSUMED_IST`). Every value keeps
  its original, normalized value and rule.

Say: *"Nothing downstream, not the database text, the logs or a model, ever sees the raw identifier. G1
checks this across 781 raw values."*

## 2. Customer and SLA, 2 min

Same page, **Customer** and **SLA** panels.

- Customer resolved `direct` from the partner record; Enterprise; region IN.
- Contract v3.2, Enterprise P3: first response 8 h (met), resolution 72 h (**breached**, 222.71 h),
  credit **3.00% = USD 88.50 (×1.5)** because resolution took more than twice the target.

Say: *"The SLA engine reproduces all 128 of Finance's Q3 credits to the cent."*

## 3. Timeline: the stale answer, 1 min

**Timeline** panel: reply by AG-001 with `kb_article_id=KB-0142` on 29 Sep, reopened on 5 Oct,
"KB article outdated" by AG-028, escalated to Jira PNJ-5188.

## 4. Routing, 2 min

**AI classification and routing** panel: `draft for agent` → **Statutory-Compliance**, L2, human
approval, **rule R7**, ruleset `route-2026.11.19`, category from the customer's pick.

- No classifier model is configured (D7), so the category is the customer's own pick, and it says so.
- Open **Processing monitor**, enter `PN-101414`: ingestion, PII, normalization, customer lookup,
  deduplication, routing and retrieval are *done*; classification *not run*; answer generation
  *unavailable* ("no drafting model configured"); human approval *pending*. Nothing pretends to have run.

## 5. Date-aware knowledge, 3 min

Open **Knowledge base → Retrieval tester**, region IN, query `PF wage ceiling`:

| As of | Top results |
|---|---|
| 15 Jun 2026 | KB-0142, KB-0143 (valid until 31 Jul), rule R-IN-PF-2026-08 **v1**: INR 15,000 |
| 15 Sep 2026 | rule R-IN-PF-2026-08 **v2** (from 1 Aug): INR 25,000. KB-0142 and KB-0143 are **not returned** |

Say: *"The articles carry no effective dates. Their validity is derived from the rule that superseded
them, and filtering happens in SQL before ranking. A September question cannot retrieve the June answer.
Replaying all 48 tickets that were answered from stale articles retrieves 0 stale chunks."*

## 6. The review item, 3 min

Open **Review queue**, reason **Statutory answer**. PN-101414 is on page 4 (items are ordered by ticket
age, blocked items first). Open it.

- **Evidence pack:** summary, customer and tier, SLA breached with USD 88.50 exposure, routing reason,
  PII tokens `<AADHAAR_1>`, `<PAN_1>`.
- **Knowledge in force on 28 Sep:** R-IN-PF-2026-08 v2, KB-0144, the payroll-week runbook. KB-0142 is absent.
- **Statutory rates in force:** EPF ceiling **INR 25,000 per month**.
- **Suggested response:** none: "No drafting model is configured; the reviewer writes the reply."

## 7. Validation and the two-person rule, 3 min

As the first approver (`agent_l2`):

1. Save the draft *"The ceiling is INR 15,000 per month (KB-0142)."* → validation **fails**
   (`statutory_values_current`, `citations_in_force`). **Approve** is refused (422).
2. Replace it with *"From 1 Aug 2026 the EPF wage ceiling is INR 25,000 per month (R-IN-PF-2026-08)."*
   → validation passes.
3. Try to approve as the same user → refused (403): R7 needs a second person.
4. Sign in as the second approver and approve. The approved reply becomes **learned memory** citing
   R-IN-PF-2026-08 v2 and expires if that rule is superseded.

Say: *"No AI output is ever stored as memory unless a person approved it. The platform has no way to move
money or change payroll."*

## 8. Sensitive data access, 1 min

As the **admin**, the ticket shows no reveal control: admins cannot read originals. As the **DPO**, reveal
`<AADHAAR_1>` with a reason of at least 10 characters. Then open **Audit log**: the entry records who,
which token and why, never the value.

## 9. Duplicate and incident scenario, 2 min

Open **Incidents & duplicates**.

- **Meridian Foods** (C-1002), payroll, 25 Sep 2026: **30 tickets** grouped into one incident (rule I1:
  5 or more tickets in one category, each within 3 h of the previous). Declared at the 5th ticket,
  **14.8 minutes** after the first. In the source data it took about 6.6 hours to escalate and 19.7 hours
  to open the Jira ticket.
- A resubmission, e.g. Kestrel Logistics `PN-101111` (rule D1: the new ticket cites the earlier id).
  Tickets are grouped into one case, not merged: each keeps its channel and messages.

Then **Review queue**, first item **PN-101129**: instructions aimed at an AI, lane `block`, queue
Security-Review. **Approve** is refused (409); it can only be escalated.

## 10. Measured results, 2 min

- **Evaluations:** G1 pass · G2 not run (baseline 84.85%) · G3 fail (25/26) · G4 pass · G5 partial ·
  G6 pass · G7 partial. Open G3 to show the failed case (PN-101510, two possible originals, flagged for
  a person) and G4's history (first run 0.40 recall, kept).
- **Cost analytics:** baseline USD 6.03 per ticket; expected scenario +USD 1,403.40/month, conservative
  −USD 462.25/month, all within the USD 4,500 cap; each input labelled measured, source estimate or
  assumption.

Close with what is not done: model access (G2, drafting, faithfulness, model latency and cost), the
review of 201 routing labels, row-level security, and the AWS deployment.

## Likely questions

| Question | Answer |
|---|---|
| Why is G3 a fail at 96%? | The target is 26/26. The miss had two originals with the same subject; the system flagged it at 0.6 confidence instead of guessing. |
| Is G4's 100% real? | On this set, yes, but the rules were improved using this set after a 40% first run. A held-out red-team set is needed for an unbiased figure. |
| Why no classification accuracy? | No model is configured (D7), and the 201 changed-queue labels need human review (D3). Reporting a number without both would be invented. |
| Can the AI refund a customer? | No. There is no endpoint that moves money; drafts promising it fail validation; R6/R7 need two people. |
| Where does UAE data live? | Same database, isolated by region scope on every query (D5). Database row-level security and a UAE region are pending. |
