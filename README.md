# Finance App

Personal finance and portfolio application in active migration from a Next.js-first
backend toward a Python backend with PostgreSQL as the shared persistence layer.

## Current State

The application is not a finished product yet. The repository currently contains:

- `Next.js 14` frontend in TypeScript.
- Existing Next.js/TypeScript backend routes that still power parts of the current UI.
- `FastAPI` Python backend under `backend/python`.
- PostgreSQL 16 database.
- Prisma as the current production migration owner.
- Complete SQLAlchemy read-only mirror of the current Prisma-managed schema.
- Alembic configured with a no-op baseline revision, ready for a future migration cutover.

Important database ownership rule:

- Prisma still owns schema migrations.
- SQLAlchemy is a runtime and verification mirror.
- Alembic is configured and verified, but does not own application tables or enums yet.
- No app startup path should run schema creation, Alembic stamp, or Alembic upgrade.

## Stack

- Frontend: Next.js 14, React, TypeScript, Tailwind CSS
- Current auth/UI integration: NextAuth
- Python API: FastAPI, SQLAlchemy 2.x async engine, asyncpg
- Database: PostgreSQL 16
- Current migration owner: Prisma
- Future migration target: Alembic
- Tooling: uv, Ruff, mypy, pytest, Vitest, Docker Compose

## Local Development

Create or update `.env` from `.env.example` first.

Start the full local stack:

```bash
docker compose up --build
```

Services:

```text
Next.js frontend: http://localhost:3000
Python API:       http://localhost:8010
PostgreSQL:       localhost:5433
```

Useful API endpoints:

```text
GET http://localhost:8010/api/v1/health/live
GET http://localhost:8010/api/v1/health/ready
GET http://localhost:8010/api/v1/portfolio?user_id=<user-id>
GET http://localhost:8010/docs
```

Start only the Python API and database:

```bash
docker compose up api --build
```

Start the Next.js app locally outside Docker:

```bash
npm install
npm run db:generate
npm run dev
```

## Database Workflow

Current Prisma commands:

```bash
npm run db:generate
npm run db:deploy
npm run db:validate
npm run db:studio
```

For local development with a disposable database, `npm run db:migrate` is available, but
production-like verification uses committed Prisma migrations with `db:deploy`.

The canonical PostgreSQL schema baseline lives in:

```text
backend/python/database/baseline/schema.sql
backend/python/database/baseline/schema.sha256
backend/python/database/schema_ownership.toml
```

Verify a migrated PostgreSQL database against the committed baseline:

```bash
cd backend/python
uv run python scripts/database_schema.py --check
uv run python scripts/sqlalchemy_schema.py --check
```

Verify Alembic baseline readiness before any manual stamp:

```bash
cd backend/python
uv run python scripts/alembic_baseline.py --verify
```

Alembic baseline commands are explicit operator actions only:

```bash
cd backend/python
uv run alembic -c alembic.ini stamp 3d0001base
uv run alembic -c alembic.ini current --check-heads
uv run alembic -c alembic.ini check
uv run alembic -c alembic.ini upgrade head
```

These commands must not change application schema objects. The baseline revision is a
marker for the inherited Prisma schema.

## Python Backend

Python backend setup:

```bash
cd backend/python
uv sync --frozen --extra dev
uv run uvicorn app.main:app --reload --port 8010
```

Windows bootstrap:

```powershell
cd backend/python
.\bootstrap.ps1 -RunChecks
```

Backend quality gate:

```bash
cd backend/python
uv run python scripts/check.py
```

Equivalent individual checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## Frontend And TypeScript Checks

```bash
npm run test
npm run lint
npm run format:check
npm run build
```

Some current product workflows still depend on the legacy Next.js backend routes while the
Python API migration continues.

## Documentation

Planning and architecture documentation lives in:

```text
!planning/
!docs/
backend/python/README.md
backend/python/database/README.md
backend/python/app/db/README.md
```

The most relevant current planning documents are:

```text
!planning/02-roadmap.md
!planning/03-modules.md
!planning/05-domain-model.md
!planning/06-project-structure.md
```

## Current Milestone Notes

Recently completed backend migration steps:

- Step 3C: complete SQLAlchemy schema mirror.
- Step 3D: Alembic baseline readiness.

Still not completed:

- Full cutover from Prisma-owned migrations to Alembic-owned migrations.
- Full removal of domain backend logic from Next.js route handlers.
- Shared production auth/session boundary between Next.js and Python API.
- Production-ready import, portfolio, snapshot, and dashboard workflows fully served by
  Python API.

## Safety Rules

- Do not edit old Prisma migrations to hide drift.
- Do not regenerate the canonical SQL baseline unless the schema change is intentional.
- Do not call `Base.metadata.create_all()` or `Base.metadata.drop_all()` in application
  runtime.
- Do not run Alembic stamp or upgrade automatically during FastAPI startup.
- Do not treat SQLAlchemy metadata as the migration owner until the ownership cutover is
  explicitly approved.
