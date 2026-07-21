# Local Setup

## Prerequisites

- Node.js and npm for Next.js, Prisma Client tooling, and repository scripts.
- Python 3.12.10 and `uv` for `backend/python`.
- Docker Desktop for PostgreSQL 16 and the optional full local stack.
- Rust only when working on `backend/rust`.

Copy `.env.example` to `.env` and set local values. For protected Python API
testing also set a shared `INTERNAL_AUTH_SECRET` (at least 32 characters in
production) plus the corresponding issuer and audience if defaults are changed.
The included compose file does not set this secret, so protected FastAPI calls
will return `503` until it is supplied.

## Start PostgreSQL and initialize its schema

```powershell
docker compose up db -d
npm run db:bootstrap
```

`db:bootstrap` is for a new, empty database. For an existing database already
on the Alembic revision graph, use `npm run db:migrate` or `npm run db:check`.
Do not run Prisma Migrate for ordinary development; the Prisma archive is frozen
and Alembic owns schema changes.

## Run services

```powershell
# repository root: Next.js UI
npm run dev -- -p 3010

# backend/python: install once, then run FastAPI
uv sync --frozen --extra dev
uv run uvicorn app.main:app --reload --port 8010
```

FastAPI listens on `http://localhost:8010`; inspect liveness at
`/api/v1/health/live` and, with a database, readiness at
`/api/v1/health/ready`. `docker compose up api --build` starts the API and
database; `docker compose up --build` also starts the Next.js container.

If Next.js reports missing chunks or an undefined module call, stop its dev
server, remove `.next`, and restart it. Avoid `npm run build` while a dev server
is running.
