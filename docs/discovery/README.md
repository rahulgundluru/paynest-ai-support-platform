# Phase 0 – Discovery summary

Source: [niti007/paynest-support-discovery](https://github.com/niti007/paynest-support-discovery) at commit `502e718`
(mirrored locally into `data/source/`, verified by `data/source_manifest.json`).
The case data is a **simulation** (the upstream names the client "Ramco Payce"; ticket ids keep the `PN-` / `PNJ-` prefixes).
This platform uses the fictional name **PayNest** and no third-party branding.

Tags: **[V]** verified by profiling the data · **[D]** stated in a source document · **[R]** recommendation · **[A]** assumption.

## 1. Approved decisions (2026-11-19)

| # | Decision | Consequence |
|---|---|---|
| D1 | Product is branded PayNest | No Ramco names or logos in UI or docs |
| D2 | RAG uses only content that exists (4 statutory rules, 4 KB excerpts, KB metadata, SOPs) | Title-only KB topics return "insufficient evidence" and route to a human |
| D3 | Routing ground truth = final queue; the 201 changed-queue tickets + a stratified sample are reviewed by the project owner | Labels stay `candidate` until signed off |
| D4 | Synthetic adversarial / planted-draft cases allowed | Stored separately and labelled `synthetic` |
| D5 | MVP runs in one AWS region with logical region isolation; UAE stack added after local validation | Residency gap documented, not hidden |
| D6 | This repository is public → source data is **not committed** | `scripts/source_data.py fetch` + manifest |
| D7 | AWS account with Bedrock access required from Phase 3 | **Pending** |

## 2. Data inventory

| File | Records | Notes |
|---|---|---|
| `data-room/data/tickets_export.json` | 1,367 rows / 1,353 unique ids | 3 schemas: email 665, widget 483, partner 219 rows [V] |
| `data-room/data/whatsapp_export.json` | 112 threads / 393 messages | ticket ids not in the export [V] |
| `data-room/data/call_center_notes.json` | 61 calls | 12 without ticket id, 7 without customer [V] |
| `data-room/data/customers.csv` | 60 | Enterprise 12, Business 18, Standard 30 [V] |
| `data-room/data/sla_breaches_q3.csv` | 128 | USD 19,195.95; every credit reproducible from the contract formula [V] |
| `data-room/data/csat_survey.csv` | 435 | 3 duplicate ticket rows [V] |
| `data-room/data/jira_escalations.json` | 62 issues | 120 linked tickets, all present in export [V] |
| `data-room/data/kb_articles.json` | 24 | metadata only; 4 excerpts; no effective dates [V] |
| `data-room/data/agent_roster.csv` | 49 | 42 active (24/12/6), 7 left Apr–Sep [V] |
| `data-room/data/monthly_cost_sheet.csv` | 6 months | USD 90,460/month support cost; USD 5.71–6.37 per ticket excl. credits [V] |
| `data-room/integrations/statutory_rules.json` | 4 rules | PF ceiling 15,000→25,000 from 2026-08-01; WPS SIF v2→v3 from 2026-07-15 [V] |
| `data-room/integrations/contract_db_schema.sql` | DDL only | no contract rows exist |
| `data-room/integrations/payroll_api_openapi.yaml` | spec only | host is not live |

## 3. Canonical ticket field mapping

| Canonical | Email | Widget | Partner |
|---|---|---|---|
| id | `ticket_id` | `tkt` | `reference` |
| customer | `customer_id` | `org_id` | `tenant` (65 unique null → `end_customer` exact name match, 65/65) |
| subject / body | `subject` / `body` | `title` / `message` | `summary` / `details` |
| priority | `P1–P3` | `urgent/high/normal` → P1/P2/P3 | `S1–S3` → P1/P2/P3 (verified against `created` event) |
| created | ISO +05:30 | naive IST | `DD/MM/YYYY HH:MM IST\|GST` |
| events | `events{event,ts,actor,meta}` | `history{action,time(epoch ms),who,data}` | `activity_log{evt,when(naive IST),user,info}` |

**Label-leak warning [V]:** the header category (`category`/`cat`/`topic`) equals the *final* queue for all 1,327 routed tickets.
The customer's original pick is only in the `created` event. Classifier inputs must never include the header category.

## 4. Key verified figures

- Payroll window (25th–3rd, IST): 951 / 1,353 tickets = 70.3%.
- Routed tickets 1,327; 26 unrouted = cross-channel resubmits resolved "duplicate of PN-…".
- 260 of 1,367 rows have a reassignment; 201 unique tickets end in a different queue than they started.
- Payroll/statutory tickets with ≥2 cross-queue moves: 75 / 303 in the window (24.8%) vs 2 / 39 outside.
- Stale KB citations: 48 replies (KB-0142/0143 after 1 Aug; KB-0201/0202 after 15 Jul), 38 reopened (79.2%); control 29, 1 reopened.
- Credits: misroute-only 35.8%, stale-only 14.6%, both 9.5% → 59.9% (USD 11,503.80); How-To = 30.6% of tickets, 4.8% of credits.
- PII: 103 export tickets carry Aadhaar/PAN/IBAN/Emirates ID/IFSC+account (session notes say 101; to reconcile in Phase 2).
- Prompt injection: one ticket, PN-101129.
- Incidents: Meridian (C-1002) 33 tickets on 25 Sep; Kestrel PNJ-4412 48 linked tickets.

## 5. Data-quality issues to handle in Phase 2

Duplicates (14 ids, 9 exact copies) · 35 category spellings · 3 priority vocabularies · 8 status spellings and no
"Pending - customer" status (SLA exclusion cannot apply) · mixed timezones (naive = IST supported for email/widget/partner;
calls unverified) · 106 blank first-response fields (80 derivable from events) · conflicting incident thresholds
(escalation policy "5+ customers" vs runbook "5+ employees of one customer") · cost-sheet extract counts ≠ export counts ·
no contract template version per customer.

## 6. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Bedrock not available in UAE region | Residency for UAE inference | Verify before Phase 7; document; DPO sign-off |
| Thin KB corpus | Limited RAG demonstration | D2; rule store is authoritative for values |
| Noisy routing labels | G2 ≥95% may be unreachable | D3 human review; report confusion matrix honestly |
| Two regional stacks | Doubles infra cost | D5; measured cost model |
| Drafting latency | 3 s first-token target | Streaming, small model for intake, cache |
| Source licence unknown | Redistribution | D6: data not committed |
