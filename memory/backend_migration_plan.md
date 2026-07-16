# Backend Migration Plan

Goal: keep the current Next.js frontend working while moving backend/domain logic to Python and Rust.

## Target Shape

- Frontend: Next.js + TypeScript.
- BFF/adapters: thin Next.js API routes during migration.
- Backend API: Python FastAPI.
- Background jobs: Python Celery or RQ.
- Calculation engines: Rust crates called by Python.
- Database: PostgreSQL, Prisma schema remains the source of truth for now.

## Migration Slices

### 1. Health And Infrastructure

- Add FastAPI app with `/health`.
- Add Rust workspace with a small tested calculation crate.
- Add local run/test docs.
- Keep current TypeScript routes untouched.

Status: started.

### 2. Read-Only Portfolio API

- Add FastAPI endpoint that returns portfolio/account read model from existing DB.
- Keep Next `/api/portfolio` as adapter.
- Compare FastAPI response against current TypeScript response for the same account.

Status: started.

Implemented first slice:

- `GET /portfolio?user_id=<user-id>&account_id=<optional-account-id>` in FastAPI.
- Read-only PostgreSQL access via `asyncpg`.
- Portfolio repository/service split.
- Basic holding cost conversion into account currency using latest stored `ExchangeRate`.
- Python backend runs independently on port `8010` to avoid common local port conflicts.
- Docker service `api` can run the Python backend next to the existing Next app.
- `npm run api:compare:portfolio` compares the Python endpoint with the current Next endpoint.

Still missing:

- Shared auth/session handling between Next.js and FastAPI.
- Live price lookup parity with the TypeScript endpoint.
- Snapshot-based current-day read model.
- Deeper parity checks for positions, warnings, cash, realized/unrealized P&L, and account currency totals.

Acceptance:

- Existing portfolio UI works without visible change.
- TypeScript and Python endpoints return equivalent totals for fixtures/current DB.

### 3. Ledger Replay Engine

- Define Rust input/output DTOs for investment events and movements.
- Implement deterministic ledger replay in Rust.
- Python loads events from DB, calls Rust, returns ledger snapshot.
- Keep TypeScript implementation until parity tests pass.

Acceptance:

- Rust and TypeScript ledger replay match on parser fixtures and real import samples.

### 4. Snapshot Builder

- Move daily snapshot calculation to Rust.
- Python job orchestrates loading prices/FX/events and saving snapshots.
- Next import flow triggers Python job instead of in-process TypeScript job.

Acceptance:

- Snapshot counts and values match current implementation for known fixtures.
- Current-day snapshot starts from latest daily snapshot and applies only later events.
- Invested/deposited values use event-date FX in account currency.

### 5. Imports And Jobs

- Move import orchestration to Python.
- Keep parser parity tests before moving individual parsers.
- Multi-file imports should enqueue one account/source post-process job.
- Unsupported rows remain parse issues.

Acceptance:

- Upload returns quickly.
- Background status is pollable.
- Failed jobs persist useful errors.

## Rules During Migration

- Do not create duplicate business rules in TypeScript, Python, and Rust without parity tests.
- Keep DB writes centralized per workflow.
- Prefer read-only FastAPI endpoints before moving write paths.
- Every migrated slice needs a rollback path to the current TypeScript implementation.
- Avoid `npm run build` while `next dev` is running.
