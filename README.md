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
| 3 AI pipeline | Classification, dedupe, routing, KB, date-aware RAG | Pending |
| 4 Human & security | Approvals, output validation, injection handling, cache, memory | Pending |
| 5 Frontend | All screens on real APIs | Pending |
| 6 Evaluation | G1–G7 runners, reports, CI gates | Pending |
| 7 AWS | Deployment | Pending |
| 8 Delivery | Docs, diagrams, demo, presentation | Pending |

Screens for unbuilt modules appear in the navigation as non-interactive "Phase N" entries; no screen shows
estimated or placeholder business metrics.

## Layout

```
backend/          FastAPI app (app/), Alembic migrations, pytest suite
frontend/         Next.js App Router UI (TypeScript, Tailwind, TanStack Query, RHF + Zod)
data/             source manifest (source data itself is fetched, not committed)
docs/             discovery, architecture, security, evaluation, deployment docs
infrastructure/   docker init scripts (AWS IaC in Phase 7)
scripts/          source data fetch/verify
.github/workflows CI: lint, type check, reversible migrations, tests, image builds
```

## Getting started

```bash
cp .env.example .env                     # then set POSTGRES_PASSWORD and JWT_SECRET
python scripts/source_data.py fetch      # pulls the pinned source data into data/source/
docker compose up --build                # db, migrate, api (:8000), web (:3000)
docker compose exec api python -m app.cli ingest   # or "Run ingestion" on the Data ingestion page
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
