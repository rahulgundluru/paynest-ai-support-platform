# Security and privacy

The pilot processes **simulated** data from the case repository. The controls below are implemented
and tested; that does not make the platform compliant with any regulation. Before any real customer
ticket is processed, the DPIA questions in section 4 must be answered by PayNest's DPO.

Related: [role and permission matrix](rbac.md) · [API access per endpoint](../api/README.md) ·
[approval and validation design](../architecture/human-approval-security.md).

## 1. Controls

Status: **Implemented** = in code and covered by tests; **Partial** = in code, with the gap described; **Pending** = not built.

| Control | Status | How | Evidence |
|---|---|---|---|
| Authentication | Implemented | Argon2id hashes; JWT bound to a server-side `auth_sessions` row, so logout and deactivation revoke at once; httpOnly cookie | `tests/test_auth.py` |
| Role-based access | Implemented | Permissions defined in `app/core/rbac.py`, checked per endpoint | [rbac.md](rbac.md); every endpoint except login and health requires sign-in |
| Region isolation (India / UAE) | Partial | Every query is filtered to the user's region scope; tickets of unknown region are visible only to users scoped to both. PostgreSQL row-level security is **pending**: it needs a non-owner database role, planned with the AWS database (Phase 7) | Region tests in the Phase 2–5 suites |
| PII redaction | Implemented | Format detectors (IBAN, Emirates ID, bank account, IFSC, PAN, Aadhaar, email, phone) replace values with `<TYPE_n>` tokens before storage; a failed checksum never un-redacts | G1: 0 leaks across 781 raw values; `tests/test_pii_gate.py` covers every type |
| PII never reaches a model | Implemented | Model payloads carry redacted text only; `assert_no_pii` blocks any payload that still matches a pattern | G1 `model_payload_leaks = 0` |
| Person-name detection | Pending | No NER model configured; Presidio is the candidate | Stated in the [data pipeline](../architecture/data-pipeline.md#known-limitations) limits |
| Protected originals | Implemented | Originals in `pii_vault` and `source_records.raw_encrypted`, Fernet-encrypted with `PII_VAULT_KEY` | Phase 2 tests |
| Original-data access | Implemented | DPO only (admins excluded); one token per request, reason of at least 10 characters, audit entry without the value | `tests/test_phase4_acceptance.py` |
| Retention | Partial | Every vault value carries `retention_until` (365 days, an assumption pending the DPO); reveal returns 410 after it. **No purge job deletes expired values yet** | `app/api/v1/approvals.py` |
| Prompt-injection defence | Implemented (rules layer) | Rule-based screen before any model; instruction/data separation in the prompt; no privileged tools; blocked items cannot be approved; validation rejects injection echoes | G4: PN-101129 blocked, 20/20 synthetic attacks, 0 false positives on 1,525 real tickets (optimistic, see G4 note) |
| Output validation | Implemented | PII, financial promises, other customers' names, superseded statutory values, citations in force | G6: 17/17 planted drafts caught |
| No financial actions by AI | Implemented | No endpoint moves money, approves refunds or edits payroll; payroll access is read-only by design | Code review; G4 `privileged_actions_executed = 0` |
| Two-person rule | Implemented | Pay/billing P1 (R6) and statutory (R7) drafts need a second approver | Phase 4 acceptance test |
| Audit log | Implemented | `audit_logs` append-only, enforced by a database trigger; logins, reveals, decisions, settings changes | Phase 1 and 4 tests |
| Rate limiting | Partial | Login: 10 attempts per 5 minutes per (email, client), returns 429. In-process, so per instance; a global limit (WAF) belongs with the AWS deployment | `tests/test_validation_ratelimit.py` |
| Request logging without sensitive values | Implemented | Method, path, status, duration and request id only; no bodies or query strings | `app/main.py` |
| Secrets management | Partial | All secrets come from the environment; none in the repository; the settings API never returns them. A managed secret store (AWS Secrets Manager) is pending | Settings test asserts the JWT secret and vault key are not returned |
| Encryption in transit | Pending | Local runs use plain HTTP on localhost only; `COOKIE_SECURE=true` is the default for TLS deployments | — |
| Encryption at rest (database) | Partial | Sensitive columns are application-encrypted; full-disk/database encryption depends on the hosting (RDS with KMS planned) | — |
| Static checks and CI | Partial | ruff (including bandit rules `S`), mypy strict, eslint, tsc, reversible migrations, tests and evaluation gates all pass locally. The CI workflow that runs them (and blocks on G1/G4/G5/G6) has not run on GitHub yet: the branch is not pushed | `.github/workflows/ci.yml` |

## 2. Threats considered

| Threat | Mitigation | Residual risk |
|---|---|---|
| Customer text tells the assistant to approve a refund or reveal data | Rule screen, untrusted-data wrapping, no privileged tools, approval required, validation | The rule screen was tuned on its own test set; a held-out red-team set is still needed |
| PII leaks to a model provider or logs | PII gate, boundary check, log policy | Person names are not detected |
| An agent sees another region's data | Region filters on every query | No database-level enforcement yet (row-level security pending) |
| A wrong statutory value reaches a customer | Date-aware retrieval, `statutory_values_current` check, two-person approval | Covers the four source rules only |
| Insider reads original identifiers | DPO-only reveal, reason required, audited, admins excluded | Database administrators with the vault key can still decrypt |
| Brute-force login | Rate limiter, Argon2id | Limit is per instance |
| Session theft | httpOnly cookie, server-side revocation, same-origin proxy | `Secure` flag requires TLS |

## 3. Data inventory

| Data | Where | Protection |
|---|---|---|
| Ticket text (subject, body, messages, events) | `tickets`, `ticket_messages`, `ticket_events` | Tokens only |
| Original identifiers | `pii_vault` | Fernet-encrypted, region-tagged, retention date |
| Original source records | `source_records.raw_encrypted` | Fernet-encrypted |
| Customer master (company names, tier, region) | `customers` | Region-scoped reads |
| Staff accounts | `users`, `auth_sessions` | Argon2id hashes; sessions revocable |
| Drafts and approved replies | `approvals`, `learned_memory` | Tokens only; memory scoped to customer and region |
| Audit trail | `audit_logs` | Append-only; values never recorded for reveals |

## 4. DPIA-oriented notes (for the DPO)

These are the questions a Data Protection Impact Assessment must answer before real data is used.
They are listed, not answered: the answers belong to PayNest.

| Topic | What the pilot does today | Decision needed |
|---|---|---|
| Purpose | Route, deduplicate and draft replies to payroll support tickets | Confirm purpose and lawful basis for India (DPDP Act 2023) and the UAE (PDPL) |
| Data minimisation | Identifiers are tokenised at ingestion; models receive redacted text only | Whether originals need to be kept at all, or only the token |
| Retention | 365 days per vault value (assumption); no purge job | Retention period per data class; build the purge job |
| Residency | One database with logical region isolation (decision D5) | Whether UAE data must stay in-country; whether the chosen model is available in-region (risk register) |
| Model provider | None configured; adapter targets AWS Bedrock | Approve the provider, region and data-processing terms |
| Access | DPO-only reveal; region scopes per user | Approve the role matrix and who holds the DPO role |
| Data subject rights | Not implemented (no export or erasure endpoint) | Required flows and response times |
| Breach handling | Audit log and request ids exist; no alerting | Incident process and notification duties |

## 5. Open security work

1. PostgreSQL row-level security with a non-owner application role.
2. Purge job for expired vault values and an erasure flow.
3. Person-name detection (NER).
4. TLS, managed secrets, WAF rate limiting and KMS keys (all part of the paused AWS phase).
5. A held-out red-team set for G4 and the Promptfoo model-level run (needs model access, D7).
6. End-to-end browser tests: the Phase 4 proxy bug showed that API tests alone miss integration faults.
