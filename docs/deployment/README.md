# Deployment guide

| Target | Status |
|---|---|
| Local, without Docker (embedded or installed PostgreSQL) | **Verified**: this is how every phase was built and tested |
| Local, Docker Compose | Written; **not verified** (Docker could not run on the build machine). The CI `images` job builds both images but has not run yet, because the branch has not been pushed |
| AWS | **Paused** (Phase 7). No infrastructure code exists and nothing is deployed |

## 1. Prerequisites

- Python 3.12, Node 22 with pnpm, PostgreSQL 16 with the `vector` extension (or Docker).
- Git access to the public source repository: the case data is fetched, not committed (decision D6).

```bash
python scripts/source_data.py fetch
```

```bash
python scripts/source_data.py verify
```

`fetch` clones the pinned upstream commit `502e718` into `data/source/` (git-ignored) without the
trainer answer key; `verify` checks every file against the SHA-256 values in `data/source_manifest.json`.

## 2. Configuration

All configuration comes from environment variables; nothing secret is in the repository.
Copy `.env.example` to `.env` for Docker, or export the variables for a local run.

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+asyncpg://user:pass@host:port/db` |
| `JWT_SECRET` | yes | Session signing secret, at least 32 characters |
| `PII_VAULT_KEY` | yes | Fernet key for the PII vault and encrypted raw records. **Losing it makes originals unrecoverable** |
| `DATA_SOURCE_DIR` | for ingestion | Path to the fetched source mirror (default `../data/source`) |
| `COOKIE_SECURE` | no | `true` by default; set `false` only for plain-HTTP localhost |
| `CORS_ORIGINS` | no | Only needed if a browser calls the API directly (the web proxy makes this unnecessary) |
| `PII_RETENTION_DAYS` | no | 365 by default; an assumption pending the DPO |
| `LLM_PROVIDER`, `EMBEDDING_PROVIDER` | no | `none` (default) or `bedrock` |
| `BEDROCK_REGION`, `BEDROCK_CLASSIFIER_MODEL_ID`, `BEDROCK_EMBEDDING_MODEL_ID` | with Bedrock | Confirm in-region model availability first |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | no | 0.80 by default |
| `TEST_DATABASE_URL` | tests | A disposable database; tests truncate it |
| `API_INTERNAL_URL` | web | Where the Next.js proxy reaches FastAPI (default `http://localhost:8000`) |

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 3. Local run without Docker (verified)

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
cd backend && alembic upgrade head
```

```bash
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend && pnpm install && pnpm build && API_INTERNAL_URL=http://127.0.0.1:8000 pnpm start
```

Then build the pipeline state once, in this order (each step is idempotent):

```bash
cd backend && python -m app.cli ingest && python -m app.cli index-knowledge && python -m app.cli detect-duplicates && python -m app.cli route-all && python -m app.cli build-review-queue
```

Create the first user (the password is read from `PAYNEST_NEW_USER_PASSWORD`, so it never lands in
shell history):

```bash
cd backend && python -m app.cli create-user --email you@example.com --name "Your Name" --role admin --region IN --region UAE
```

Roles: `agent_l1`, `agent_l2`, `engineer_l3`, `support_lead`, `kb_owner`, `dpo`, `finance_viewer`,
`admin`. A demo needs an `admin`, a `dpo`, an `agent_l1`, and two users who can decide approvals (`agent_l2`,
`support_lead` or `admin`) to show the two-person rule.

Run the evaluation gates and write the report:

```bash
python evaluations/run_evaluations.py
```

## 4. Local run with Docker Compose (not verified locally)

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

Compose starts `db` (pgvector/pg16, port bound to 127.0.0.1), runs `migrate` once, then `api` (:8000)
and `web` (:3000), and mounts `./data` read-only. Run the CLI steps above with
`docker compose exec api python -m app.cli …`.

## 5. Health checks

| Endpoint | Meaning |
|---|---|
| `GET /health` | Process is up; touches nothing else |
| `GET /ready` | Database reachable, migration head applied, pgvector installed, e.g. `{"status":"ok","checks":{"database":"ok","migration":"0006_evaluation","pgvector":"ok"}}` |
| `GET /system/ready` (web) | The web app can reach the API |

Both Dockerfiles define a `HEALTHCHECK`; containers run as a non-root user (uid 10001).

## 6. Database migrations

Migrations are the only way the schema changes. CI proves every migration is reversible
(`alembic upgrade head && alembic downgrade base && alembic upgrade head`). Run `alembic upgrade head`
before starting a new API version.

## 7. AWS (Phase 7, paused)

Nothing below exists yet. It records the intended shape so the work can resume.

```mermaid
flowchart LR
  internet([Internet]) --> alb[Application Load Balancer<br/>TLS, WAF rate rule]
  subgraph vpc["VPC, private subnets"]
    web[ECS Fargate: web]
    api[ECS Fargate: api]
    job[ECS one-off tasks:<br/>migrate, ingest, evaluate]
    rds[(RDS PostgreSQL 16 + pgvector<br/>KMS, no public access)]
  end
  alb --> web --> api --> rds
  job --> rds
  api -. VPC endpoint .-> bedrock{{Bedrock}}
  sm[Secrets Manager] -.-> api & job
  s3[(S3: source mirror, reports)] -.-> job
  cw[CloudWatch logs, alarms<br/>AWS Budgets alerts] -.- api & web & rds
```

Prerequisites before Phase 7 can start:

1. An AWS account and a deploy role (least privilege; GitHub OIDC, no long-lived keys).
2. Model access decision (D7): Bedrock model ids available in `ap-south-1`, and whether UAE data needs
   an in-country region.
3. A purchased or delegated domain for TLS.
4. Docker working on the build machine, or image builds left to CI.
5. A budget alert threshold below the USD 4,500 cap.

Work planned for the phase: Terraform for the diagram above, row-level security with a non-owner
application role, `PII_VAULT_KEY` replaced by a KMS data key per region, CloudWatch alarms, and a
manually triggered deploy workflow. Each item must be verified in the account before it is reported done.
