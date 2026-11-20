# Evaluation framework (G1–G7) and cost model

The latest generated results are in [report.md](report.md), produced with `python evaluations/run_evaluations.py`. Every run is stored in `evaluation_runs` / `evaluation_results` and shown on the Evaluations page with its history.

## Principles

- **Report only what was executed.** A gate is `pass` or `fail` only for what actually ran. Parts that need a model are `not_run` with the reason. A gate with both executed and unexecuted parts is `partial`.
- **No side effects.** Each gate runs in a database session that is rolled back, so evaluations leave no retrieval logs behind.
- **No personal data in results.** Case details hold identifiers and outcomes only. G1 also scans the evaluation results table itself.
- **Labels never feed the system under test.** Agents' "duplicate of" resolutions and the export's final queue are used only as answer keys.

## Gates

| Gate | What runs | Dataset | Target | Blocks CI |
|---|---|---|---|---|
| G1 PII | Raw PII values extracted from the source are searched for in every stored plaintext surface; every model payload is built exactly as the classifier would send it | 835 tickets with PII, 781 raw values | 0 leaks | yes |
| G2 Classification | **Not run** (no model, D7). Reports today's baseline: the customer's own pick vs the final queue | 1,327 routed tickets (final queue as candidate label; the 201 that changed queue need human review, D3) | ≥ 95% accuracy, ≤ 5% payroll-window bounce | no |
| G3 Duplicates | Resubmission links compared with agents' labels; false merges; Meridian incident timing | 26 labelled resubmissions + Meridian | 26/26, 0 false merges, incident declared by the 5th ticket | no |
| G4 Injection | Rule-based detection on synthetic attacks and benign controls; false positives on all real tickets; PN-101129 routed to `block`; structural neutralisation | PN-101129 + 20 synthetic attacks + 10 synthetic benign + 1,525 real tickets | 100% recall, < 2% false positives, 0 privileged actions | yes |
| G5 RAG | Effective-date correctness on the stale and control sets; PF June/September checks. **Ragas faithfulness not run** (needs a model) | 48 stale + 29 control + 2 | 0 stale chunks, 0 future chunks, ≥ 0.90 faithfulness | yes |
| G6 Output validation | Planted wrong drafts and correct drafts on real tickets | 17 planted + 6 correct (synthetic drafts) | 100% caught | yes |
| G7 Speed and cost | Rule-based pipeline latency (routing + retrieval) over all tickets; recorded model usage. **First-token latency and cost per draft not run** | 1,519 tickets | p95 first token < 3 s; ≤ USD 0.02 per draft | no |

## Results history

| Gate | Result (19 Nov 2026) |
|---|---|
| G1 | **pass**: 0 leaks |
| G2 | **not run**. Baseline: 84.85% routed correctly; 24.75% of payroll-window tickets bounced |
| G3 | **fail**: 25 of 26 resubmissions linked to the right original (precision and recall 96.2%); 0 false merges; Meridian declared 14.8 min after the first ticket. The one miss, PN-101510, had two originals with the same subject; it is flagged at 0.6 confidence for a person to confirm. |
| G4 | First run **fail** (recall 0.40: missed Hindi, Hinglish and Arabic attacks, spaced-out text, fake "SYSTEM:" lines, tool-call JSON, authority claims and credential requests). The rule families were then broadened and the second run is **pass** (recall 1.0, 0 false positives on 1,525 real tickets). Because this set shaped the patterns, the second figure is optimistic; a held-out red-team set is needed. |
| G5 | **partial**: 0 stale chunks, 0 future chunks, PF dates correct; faithfulness not run |
| G6 | **pass**: 17/17 planted drafts caught. The first run wrongly rejected 1 correct draft that cited an outdated article to explain it was outdated. The validator now allows that only when the in-force replacing rule is also cited and the article is described as old; second run: 0 false rejects. |
| G7 | **partial**: rule-based pipeline p95 about 55 ms per ticket on a laptop with embedded PostgreSQL; no model calls recorded |

## Promptfoo

`evaluations/promptfoo/` holds a model-level injection regression generated from the G4 dataset (`build_tests.py` → `tests.yaml`). It is **configured but not executed**: it needs Bedrock access (D7). The CI job `promptfoo` skips itself until `PROMPTFOO_BEDROCK_MODEL` and `AWS_EVAL_ROLE_ARN` are set.

## Cost model (`/analytics/cost`, Cost analytics page)

Every input carries its provenance:

| Provenance | Source |
|---|---|
| **Measured** | Finance's cost sheet: Jul–Sep 2026 average of USD 90,460/month support cost, 15,008 tickets/month, USD 6,398.65/month credits. The SLA engine: 59.9% of credits come from misrouted or stale-answer tickets. Recorded model usage (none yet). |
| **Source estimate** | Session 4: USD 0.0155 per draft, USD 420/month for two AWS regions (USD 1,120 with managed search), USD 0.90 embeddings |
| **Assumption** | Drafts per month, share of addressable credits avoided, minutes saved per draft, FTE hours, implementation cost (user input) |

Cash savings count only avoided SLA credits. Released agent time is shown as capacity. Payback is computed only when an implementation cost is supplied, because the sources don't contain one.

| Scenario | AI platform / month | Credits avoided / month | Net / month | Within USD 4,500 cap |
|---|---|---|---|---|
| Best | USD 482.90 | USD 2,875.95 | +USD 2,393.05 | yes |
| Expected | USD 513.90 | USD 1,917.30 | +USD 1,403.40 | yes |
| Conservative | USD 1,420.90 | USD 958.65 | **−USD 462.25** | yes |
