# Cost analysis

Computed by `GET /api/v1/analytics/cost` and shown on the **Cost analytics** page, where the
assumptions can be edited. Figures below were read from that endpoint on 20 Nov 2026 with the default
assumptions. Code: `backend/app/api/v1/analytics.py`.

Every input carries one of three labels, and the page shows them:

| Label | Meaning | Examples |
|---|---|---|
| **Measured** | Computed from source data or recorded usage | Finance cost sheet, SLA engine, `model_usage` |
| **Source estimate** | Stated in the case material (Session 4 notes) | Cost per draft, AWS infrastructure, embeddings |
| **Assumption** | Chosen for the scenario; editable | Drafts per month, share of credits avoided, minutes saved |

## 1. Today's baseline (measured)

From Finance's cost sheet, July–September 2026 average, and the SLA engine on the Q3 extract.

| Measure | Value |
|---|---|
| Support cost per month | USD 90,460.00 |
| Tickets per month | 15,008 |
| Cost per ticket, excluding credits | USD 6.03 |
| SLA credits per month | USD 6,398.65 |
| Cost per ticket, including credits | USD 6.45 |
| Share of credits on misrouted or stale-answer tickets ("addressable") | 59.93% |
| Monthly budget cap for AI, hosting and search | USD 4,500 |

## 2. AI pilot cost (measured so far)

**Nothing measured yet.** No model is configured (decision D7), so `model_usage` holds 0 draft calls and
input/output token counts are zero. Per-draft cost therefore uses the case's estimate of USD 0.0155
(target ≤ USD 0.02, gate G7). The deterministic pipeline itself has no per-call cost.

## 3. Scenarios

Infrastructure is the Session 4 list-price estimate for two AWS regions (USD 420/month); the
conservative case adds a managed search service (USD 1,120/month). Embeddings: USD 0.90/month.

| | Best | Expected | Conservative |
|---|---|---|---|
| Drafts per month (assumption) | 4,000 | 6,000 | 15,000 |
| Cost per draft (source estimate) | USD 0.0155 | USD 0.0155 | USD 0.02 |
| Share of addressable credits avoided (assumption) | 75% | 50% | 25% |
| **AI platform cost / month** | USD 482.90 | USD 513.90 | USD 1,420.90 |
| Within the USD 4,500 cap | yes (USD 4,017.10 headroom) | yes (USD 3,986.10) | yes (USD 3,079.10) |
| **Credits avoided / month** | USD 2,875.95 | USD 1,917.30 | USD 958.65 |
| **Net cash effect / month** | **+USD 2,393.05** | **+USD 1,403.40** | **−USD 462.25** |
| Cost per ticket incl. credits (baseline USD 6.45) | USD 6.29 | USD 6.36 | USD 6.48 |
| Released agent capacity (4 min per draft, 160 h per FTE) | 266.67 h · 1.67 FTE | 400 h · 2.50 FTE | 1,000 h · 6.25 FTE |
| Payback | needs implementation cost | needs implementation cost | needs implementation cost |

### How to read this

- **Cash savings count only avoided SLA credits.** Released agent time is capacity, not money, unless
  staffing changes; the spec asks for this distinction.
- **Not every ticket is automated.** Drafts go to an agent, and auto-answer is locked in the pilot.
- **The conservative case loses money** (−USD 462.25/month): drafting every ticket at the target price
  with managed search costs more than a quarter of the addressable credits.
- **Payback is not computed** because the sources contain no implementation cost. Enter one on the
  Cost analytics page to get payback in months.
- **Infrastructure figures are estimates.** Verify them with the AWS Pricing Calculator before committing
  budget; actual AWS spend is not measured because nothing is deployed.

## 4. What would make these numbers measured

1. Model access (D7): `model_usage` then records real tokens, latency and cost per draft.
2. A shadow-mode run on live tickets: the share of credits actually avoided replaces the assumption.
3. An AWS deployment with budget alerts: real infrastructure cost replaces the Session 4 estimate.
