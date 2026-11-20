# Phase 5 – Frontend and analytics

All screens read live API data, scoped to the signed-in user's regions. Navigation entries appear only for roles with the matching permission. The Evaluations and Cost analytics screens were added in Phase 6 ([evaluation](../evaluation/README.md), [cost analysis](../cost-analysis/README.md)).

| Screen | Route | Data source |
|---|---|---|
| Dashboard | `/dashboard` | `/dashboard/summary`, `ticket-trends`, `breakdowns`, `sla-performance`, `routing-performance` |
| Tickets / ticket detail | `/tickets`, `/tickets/[ref]` | `/tickets`, `/tickets/{ref}`, `/tickets/{ref}/routing`, PII reveal (DPO only) |
| Processing monitor | `/processing` | `/processing/overview`, `/processing/{ref}/status` |
| Customers / customer detail | `/customers`, `/customers/[id]` | `/customers`, `/customers/{id}`, filtered tickets and cases |
| Incidents & duplicates | `/incidents` | `/duplicates`, detect, link and unlink |
| Knowledge base | `/knowledge` | documents, versions, retrieval tester, statutory rates |
| Review queue | `/review` | `/approvals` with draft, validation and decision |
| Data ingestion | `/ingestion` | `/processing/ingest`, `/processing/batches` |
| Audit log | `/audit` | `/audit-logs` |
| Settings | `/settings` | `GET` / `PATCH /settings` |
| Evaluations | `/evaluations` | `/evaluations/gates`, `/evaluations`, `/evaluations/{run_id}`, run |
| Cost analytics | `/analytics/cost` | `/analytics/cost`, `/analytics/model-usage` |

## Dashboard metrics

Every number is computed at request time. The table shows values for an all-region user on the pinned data.

| Metric | Value | Definition |
|---|---|---|
| Tickets | 1,526 | 1,353 export + 112 WhatsApp + 61 phone |
| Open | 68 | 61 phone notes (no status) and 7 open WhatsApp threads |
| SLA breaches / credits | 128 / USD 19,195.95 | Recomputed by the SLA engine; credits by ticket month |
| Waiting for a person | 288 | Pending review items |
| Grouped cases | 26 resubmissions, 2 incidents | From the detection rules |
| Median first response | 2.8 h | From recorded or derived first-response times |
| Routed right first time | 84.9% (1,126/1,327) | **Baseline only:** the customer's own pick against the final queue. G2 must beat it. |
| AI-classified tickets | 0 | No model configured; stated on screen |
| Automation rate | 0% | Auto-answer is locked in the pilot; stated on screen |
| Credits from tickets that changed queue | 45.3% | Credits on tickets with at least one cross-queue move |

## Charts

These follow the data-viz method:
- **Colour:** single-series charts in one validated colour (reference palette slot 1: `#2a78d6` light, `#3987e5` dark). Both values pass the palette validator, contrast included.
- **Legibility:** no dual axes; recessive grid and axes; a hover tooltip on every chart; a "Show table" view on every chart.
- **Payroll window:** shaded as a neutral background band rather than encoded in a series colour.
- **Line shape:** straight segments, because smoothing would invent values between days.

## Runtime settings (`/settings`)

Each runtime setting is typed and bounded. Every change is audited with its old and new value and takes effect on the next run, with no redeploy. Only admins can change them; support leads can view them.

| Key | Default | Bounds |
|---|---|---|
| `classification.confidence_threshold` | 0.80 | 0.5–0.99 |
| `dedupe.incident_min_tickets` | 5 | 3–20 |
| `dedupe.incident_gap_hours` | 3 | 0.5–24 |
| `dedupe.follow_up_window_days` | 7 | 1–30 |
| `routing.auto_answer_enabled` | false | **Locked** until shadow-mode evaluation (Phase 6) |

Model, credential and retention settings are deployment configuration and are shown read-only. Credentials are never returned by the API; a test asserts the JWT secret and vault key don't appear.

## Known limitations

- **Dates:** shown in IST. UAE local-time display is not implemented.
- **Ticket search:** the list doesn't yet read filters from the URL, so filtered views can't be bookmarked.
- **Browser tests:** no end-to-end browser suite yet; screens were checked by hand in the browser. The Phase 4 proxy bug showed a suite is needed.
