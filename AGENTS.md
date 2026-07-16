# Codex Local Instructions

Read this file before answering or changing code in this repository.

Also read:

- `memory/codex_rules.md`
- `memory/implementation_plan.md` when the task touches architecture, imports, portfolio, snapshots, database, or performance
- `memory/backend_migration_plan.md` when the task touches the Python/Rust backend migration

## Architecture Direction

- Frontend stays in TypeScript.
  - Use Next.js for the web app.
  - Prefer TanStack Query for server-state fetching/caching.
  - Prefer Lightweight Charts for portfolio/performance charts.
  - Use one UI system consistently: shadcn/ui or Mantine. Do not mix both without a clear reason.
  - Keep frontend focused on UI, routing, forms, charts, and client-side state. Do not put domain calculations in React components.
- Backend/domain logic should gradually move out of the Next.js TypeScript backend.
  - Next.js API routes should become thin adapters or BFF endpoints.
  - Domain logic should not depend on React, Next request objects, or frontend-specific types.
- Python is the primary backend language.
  - Use FastAPI for backend HTTP APIs.
  - Use Python for orchestration, imports, validation workflows, integrations, background jobs, provider calls, and application services.
  - Use Pydantic models for API/input/output validation.
  - Keep Python services modular by domain: imports, ledger, holdings, snapshots, prices/FX, accounts, portfolio read models.
- Rust is for performance-critical engines.
  - Use Rust for portfolio and account snapshot building.
  - Use Rust for investment ledger replay.
  - Use Rust for historical portfolio calculations.
  - Use Rust for large import normalization when parsing/transformation becomes CPU-heavy.
  - Use Rust for FX/price-heavy batch computations.
  - Use Rust for any CPU-heavy or high-volume data processing.
  - Rust modules should expose stable, explicit interfaces that Python can call.
  - Prefer deterministic pure calculation cores: inputs in, outputs/errors out, no hidden DB access unless intentionally designed.
- Database stays PostgreSQL.
  - Keep Prisma schema as the source of truth for the current DB model for now.
  - Migrations remain PostgreSQL SQL generated/managed through Prisma unless there is a clear reason to write SQL manually.
  - Be careful when introducing Python DB access so Prisma schema and Python models do not drift.
  - If Python needs DB access, define a clear policy first: generated clients, SQLAlchemy models, raw SQL, or service-only access through APIs.
- Background jobs should move out of Next.js.
  - Use Celery or RQ for Python background jobs.
  - Jobs should handle imports, price/FX backfills, snapshot rebuilds, ledger recalculations, and slow provider calls.
  - In-process Next.js background jobs are acceptable only as temporary scaffolding during migration.
- Inter-service boundaries should be explicit.
  - Frontend talks to Next.js BFF or directly to FastAPI only after the API boundary is stable.
  - FastAPI orchestrates application services and calls Rust for heavy calculations.
  - Rust should not know about frontend concerns.
  - DB writes should be centralized enough to avoid duplicated business rules across TypeScript, Python, and Rust.

## Migration Approach

- Do not rewrite everything at once.
- Keep the current app working while migrating.
- Prefer extracting clear domain boundaries first:
  - imports
  - ledger/events/movements
  - holdings
  - snapshots
  - prices and FX
  - portfolio/account read models
- New heavy calculation code should be designed so it can later live in Rust, even if a temporary TypeScript implementation remains.
- New backend modules should avoid being tightly coupled to React/Next route handlers.
- Next.js API routes should become thin adapters over backend services.

## Current Product Rules

- Accounts have a main currency in `Account.currency`.
- Account-level portfolio/account pages should display primary values in the account's main currency.
- Do not hard-code CZK for account snapshots.
- Invested/deposited values must use the FX rate from the event date, not today's FX rate.
- Current-day/live portfolio values should start from the latest daily account snapshot and apply only events after that snapshot.
- Keep currency breakdowns by original currency where useful.

## Verification

- For current TypeScript code, prefer:
  - `npx.cmd tsc --noEmit`
  - `npm.cmd test`
  - `npm.cmd run lint`
- Avoid `npm run build` while the user is running `next dev`; `.next` cache has repeatedly caused missing chunk/runtime errors.

## Working Style

- Be explicit when a change is temporary TypeScript scaffolding versus the desired future Python/Rust backend shape.
- Prefer small, reversible migration steps.
- Do not introduce a new Python or Rust framework without explaining why it fits the planned backend split.
