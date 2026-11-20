# Phase 2 – Data pipeline

```
source file ──► adapter ──► PII gate ──► normalization ──► customer lookup ──► SLA engine ──► persist
 (read-only)    (reshape)   (tokens +    (versioned        (deterministic,     (contract      (one savepoint
                            vault)       rules + log)      no fuzzy match)     v3.2)          per record)
```

Run it with `python -m app.cli ingest` or `POST /api/v1/processing/ingest` (roles: support_lead, admin).
Re-running is a no-op: records are keyed on (source file, record index, content SHA-256).

## Stage guarantees

| Stage | Code | Guarantee |
|---|---|---|
| Adapters | `services/ingestion/adapters.py` | One adapter per schema: email, widget, partner portal (all in `tickets_export.json`), WhatsApp, phone. They reshape only. |
| PII gate | `services/pii/` | Runs before anything except the encrypted raw record is stored. Values become `<TYPE_n>` tokens. Originals go to `pii_vault`, encrypted and region-tagged with a retention date. |
| Normalization | `services/normalization/` | Each structured value is logged with its original value, normalized value and rule id in `normalization_log`. Labels that can't be mapped go to review; they are never guessed. |
| Customer lookup | `services/customer_lookup.py` | Resolves only on a direct id or an exact legal-name match. A phone country code can give a region hint, never a customer. |
| SLA engine | `services/sla/engine.py` | Pure functions. Elapsed calendar hours, resolution measured to the final resolved event, ×1.5 above twice the target, credits on resolution misses only. |
| Persistence | `services/ingestion/pipeline.py` | Every record read is processed, flagged `requires_review` or `duplicate`, marked `failed`, or `skipped` if already ingested. None is silently dropped. |

## Normalization rules (ruleset `norm-2026.11.19`)

- **Priority:** P1–P3 as given (email); urgent/high/normal → P1/P2/P3 (widget); S1/S2/S3 → P1/P2/P3 (partner). Verified against every ticket's `created` event with no contradictions.
- **Category:** the 35 spellings found in the export map to the 9 categories of the triage SOP. The ticket stores two labels:
  - `customer_category`: the customer's original dropdown pick, taken from the `created` event. Its queue equals `first_queue` for all 1,327 routed tickets.
  - `final_category_label`: the export's header category, which is the **final, corrected** label. It is stored for evaluation only and **must never be a classifier input** (label leak).
- **Timestamps:**

  | Rule | Format |
  |---|---|
  | `TS_ISO_OFFSET` | ISO 8601 with an offset |
  | `TS_ISO_UTC_Z` | ISO 8601 ending in Z |
  | `TS_EPOCH_MS_UTC` | Epoch milliseconds |
  | `TS_LABELLED_IST` / `TS_LABELLED_GST` | Partner-portal dates labelled with a timezone |
  | `TS_NAIVE_ASSUMED_IST` | No timezone. Assumption A1, verified for email, widget and partner data. |
  | `TS_CALL_NAIVE_ASSUMED_IST_UNVERIFIED` | Phone notes. The same assumption, which couldn't be checked for this source. |

- **First response:** the header value when present, otherwise the first non-internal reply event (`FR_DERIVED_FROM_REPLY_EVENT`, 80 tickets).
- **Payroll window:** 25th–3rd on the IST calendar date.

## Phase 2 results (pinned source `502e718`)

| Measure | Result |
|---|---|
| Records read | 1,540 (export 1,367 · WhatsApp 112 · phone 61); 0 failed |
| Export tickets | 1,353 unique ids. 14 repeated ids: 11 identical after normalization (`duplicate`), 3 with conflicting status labels (`requires_review`, first copy kept) |
| Requires review | 176 records: 173 tickets plus the 3 conflicting duplicates. Reasons: WhatsApp and phone carry no priority (173); customer identity missing (57 WhatsApp + 7 phone) |
| Customer resolution | 65/65 partner tickets with a null tenant resolved by exact end-customer name; 55/112 WhatsApp threads by exact customer hint |
| PII | 103 export tickets have ID or bank data in their text (session notes say 101; the gap is still to be explained), plus 9 WhatsApp threads and 4 call notes. Sender emails and WhatsApp numbers are tokenized too. |
| G1 (deterministic) | 0 source PII values found in any stored plaintext column (`tests/test_ingestion.py`) |
| SLA | The engine finds exactly the 128 breaches on Finance's list and reproduces all 128 credits to the cent (USD 19,195.95). No breaches outside the list. |
| Routing baseline | 201 of 1,327 routed tickets ended in a different queue than their first |

## Known limitations

- **Person names are not detected.** No NER model is configured yet; the planned option is Presidio. Only format-based identifiers, emails and phones are masked.
- **Images and attachments are not handled.** The source data contains none.
- **SLA exclusion §3.5 ("Pending - customer") can't be applied.** No source system records that status.
- **Contract template version is unknown per customer.** Everyone is evaluated on v3.2 (no credit cap). This is consistent with all 128 Finance credits, but unconfirmed.
- **WhatsApp threads have no closed timestamp,** so their resolution SLA isn't computed. They also have no priority and wait for Phase 3 classification.
- **The vault key is a local Fernet key from `PII_VAULT_KEY`.** It moves to a regional KMS data key in Phase 7.
- **Retention is set to 365 days** (`PII_RETENTION_DAYS`). This is an assumption pending the DPO's decision.
- **Region scoping is enforced in application queries.** PostgreSQL row-level security is planned for Phase 4. Records with an unknown region are visible only to users scoped to both regions.
- **Ingestion runs inside the API request** (about 17 s locally). Phase 3 moves it to the worker queue.
