# PayNest AI Support Intelligence Platform

AI-assisted support operations for a (simulated) payroll SaaS operating in India and the UAE:
PII-safe ticket intake, deterministic routing, duplicate/incident detection, effective-date-aware
retrieval, human approval, and measured evaluation gates (G1–G7).

Built for the FDE Academy case [niti007/paynest-support-discovery](https://github.com/niti007/paynest-support-discovery).
All case data is synthetic; see [docs/discovery](docs/discovery/README.md) for the verified findings that drive the design.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 Discovery | Source analysis, decisions, risk register | Done |
| 1 Foundation | Repo layout, FastAPI + auth/RBAC + audit, Alembic, Next.js shell, Docker, CI | Done locally (Docker images not yet built) |
| 2 Data pipeline | Ingestion, PII gate + vault, normalization, customer/SLA lookup, ticket screens | **Done locally** ([details](docs/architecture/data-pipeline.md)) |
| 3 AI pipeline | KB with effective dates, date-aware retrieval, dedupe/incidents, deterministic routing, classifier + Bedrock adapter | **Done locally except model-dependent parts** ([details](docs/architecture/ai-pipeline.md)); G2 + embeddings need Bedrock access |
| 4 Human & security | Review queue + approval workflow, output validation (G6), learned memory, DPO-only PII reveal, rate limiting | **Done locally** ([details](docs/architecture/human-approval-security.md)); AI drafts, semantic cache and DB row-level security pending |
| 5 Frontend | Live dashboard and charts, processing monitor, customers, settings (runtime config) | **Done locally** ([details](docs/architecture/frontend.md)) |
| 6 Evaluation | G1–G7 runners + report, evaluation and cost screens, CI evaluation job, Promptfoo config | **Done locally** ([framework](docs/evaluation/README.md), [latest report](docs/evaluation/report.md)); model-dependent parts not run |
| 7 AWS | Deployment | **Paused** ([target and prerequisites](docs/deployment/README.md#7-aws-phase-7-paused)); nothing deployed |
| + Intake & AI | New ticket screen, live pipeline view, OpenRouter classification and drafting, AI management (per-ticket cost, monitoring, caps) | **Done locally** ([details](docs/architecture/ticket-intake-ai.md)); verified live with OpenRouter on single tickets (about USD 0.0006 per ticket) |
| 8 Delivery | Docs, diagrams, demo, presentation | **Done** ([delivery summary](docs/delivery/README.md), [demo script](docs/demo/README.md), [slide deck](https://claude.ai/artifact/MyRPo9jBXQDevbupyqpnHX)) |

No screen shows estimated or placeholder business metrics; anything that needs an AI model is labelled as not run.

## Documentation

| Topic | Document |
|---|---|
| What was delivered, acceptance criteria, gaps | [Delivery summary](docs/delivery/README.md) |
| Architecture and diagrams | [Overview](docs/architecture/overview.md) · [data pipeline](docs/architecture/data-pipeline.md) · [AI pipeline](docs/architecture/ai-pipeline.md) · [approval and security](docs/architecture/human-approval-security.md) · [frontend](docs/architecture/frontend.md) · [ticket intake and AI management](docs/architecture/ticket-intake-ai.md) |
| Database ER diagram | [Database](docs/database/README.md) |
| API | [API reference](docs/api/README.md) · [openapi.json](docs/api/openapi.json) · live at `/api/docs` |
| Evaluation G1–G7 | [Framework](docs/evaluation/README.md) · [latest report](docs/evaluation/report.md) |
| Security and privacy (DPIA notes) | [Security](docs/security/README.md) · [role matrix](docs/security/rbac.md) |
| Cost | [Cost analysis](docs/cost-analysis/README.md) |
| Running it | [Deployment guide](docs/deployment/README.md) |
| Demo and presentation | [Demo script](docs/demo/README.md) · [slide deck](https://claude.ai/artifact/MyRPo9jBXQDevbupyqpnHX) |
| Source data findings | [Discovery](docs/discovery/README.md) |

The API, database and role documents are generated from the code: `cd backend && python ../scripts/generate_reference_docs.py`.

## Layout

```
backend/          FastAPI app (app/), Alembic migrations, pytest suite
frontend/         Next.js App Router UI (TypeScript, Tailwind, TanStack Query, RHF + Zod)
data/             source manifest (source data itself is fetched, not committed)
docs/             discovery, architecture, database, API, security, evaluation, cost, deployment, demo
evaluations/      evaluation datasets, Promptfoo config, run_evaluations.py
infrastructure/   docker init scripts (AWS infrastructure pending, Phase 7 paused)
scripts/          source data fetch/verify, reference doc generator
.github/workflows CI: lint, type check, reversible migrations, tests, image builds
```

## Getting started

```bash
cp .env.example .env                     # then set POSTGRES_PASSWORD and JWT_SECRET
python scripts/source_data.py fetch      # pulls the pinned source data into data/source/
docker compose up --build                # db, migrate, api (:8000), web (:3000)
docker compose exec api python -m app.cli ingest             # or "Run ingestion" on the Data ingestion page
docker compose exec api python -m app.cli index-knowledge
docker compose exec api python -m app.cli detect-duplicates
docker compose exec api python -m app.cli route-all
docker compose exec api python -m app.cli build-review-queue
docker compose exec api python -m app.cli evaluate --report /tmp/report.md
docker compose run --rm -e PAYNEST_NEW_USER_PASSWORD api python -m app.cli create-user \
  --email you@example.com --name "Your Name" --role admin --region IN --region UAE
```

Open http://localhost:3000. API docs: http://localhost:8000/api/docs.

### Backend without Docker

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://...      # PostgreSQL 16 with pgvector
alembic upgrade head
uvicorn app.main:app --reload
TEST_DATABASE_URL=postgresql+asyncpg://.../paynest_test pytest
```

### Frontend without Docker

```bash
cd frontend
pnpm install
API_INTERNAL_URL=http://localhost:8000 pnpm dev
```

The browser talks only to the Next.js origin; `/api/*` is proxied to FastAPI so the httpOnly session cookie is first-party.

## Security notes (Phase 1)

- Argon2id password hashing; JWT sessions backed by a server-side session table (logout and deactivation revoke immediately).
- Role permissions are defined in code (`backend/app/core/rbac.py`); users carry region scopes (IN / UAE).
- `audit_logs` is append-only, enforced by a database trigger.
- Request logs record method, path, status and duration only; bodies and query strings are never logged.
- No credentials in the repository; `.env` and `data/source/` are git-ignored.
