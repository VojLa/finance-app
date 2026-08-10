# Finance App

Personal finance and portfolio application with a Next.js presentation layer,
FastAPI business backend, and PostgreSQL persistence.

## Runtime architecture

- Next.js 14, React, TypeScript, Tailwind CSS, and NextAuth JWT sessions.
- Thin same-origin Next.js API adapters forward authenticated requests to FastAPI.
- Python owns credentials, authorization over financial data, imports, accounts,
  transactions, budgets, investments, market evidence, snapshots, and read models.
- SQLAlchemy is the runtime persistence mapping and Alembic is the only executable
  schema migration system.
- `prisma/migrations/` is immutable historical SQL evidence only. The repository has
  no Prisma client, generator, schema mirror, deployment command, or runtime package.

## Local development

Copy `.env.example` to `.env`, then start the complete stack:

```powershell
docker compose up --build
```

The UI is at `http://localhost:3000`, FastAPI at `http://localhost:8010`, and
PostgreSQL at `localhost:5433`.

For a new empty database:

```powershell
npm run db:bootstrap
npm run seed
```

For an existing database on the Alembic graph:

```powershell
npm run db:migrate
npm run db:check
```

Run the services outside Docker with:

```powershell
npm ci
npm run dev -- -p 3010

cd backend/python
uv sync --frozen --extra dev
uv run uvicorn app.main:app --reload --port 8010
```

Next.js does not require `DATABASE_URL`; only the Python service and database
operator scripts connect to PostgreSQL.

## Verification

Frontend:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run api:python:check
npm run format:check
```

Backend:

```powershell
cd backend/python
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run python scripts/migration_policy.py --check
```

The PostgreSQL integration tests require an explicit dedicated `DATABASE_URL`.
Do not run `npm run build` while `next dev` is active because both processes share
the `.next` cache.

## Database safety

- Do not edit the files under `prisma/migrations/`; their aggregate SHA-256 is
  verified as a frozen archive.
- Add schema changes only as reviewed Alembic revisions with revision-specific SQL
  artifacts and SQLAlchemy parity.
- Never call `create_all`, `drop_all`, stamp, or upgrade from application startup.
- `db:bootstrap` refuses a non-empty public schema; normal upgrades use an advisory
  lock and verify the committed schema artifact after migration.

## Documentation

Current architecture is documented in [`!docs/`](!docs/), planned scope and
decisions in [`!planning/`](!planning/), and execution/audit records in
[`ChatGPT/`](ChatGPT/).
