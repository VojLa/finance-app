# Local Setup

## Prerequisites

- Node.js and npm for the Next.js presentation layer and repository scripts.
- Python 3.12.10 and `uv` for `backend/python`.
- Docker Desktop for PostgreSQL 16 and the optional full local stack.
- Rust only when working on `backend/rust`.

Copy `.env.example` to `.env` and set local values. The committed
`development-internal-auth-secret-change-me` value is only a local placeholder;
replace it with a secret-manager value in deployed environments. The Next.js
adapter and FastAPI must share `INTERNAL_AUTH_SECRET`,
`INTERNAL_AUTH_ISSUER`, and `INTERNAL_AUTH_AUDIENCE`.

Next.js additionally uses:

| Variable                          | Local default           |
| --------------------------------- | ----------------------- |
| `PYTHON_BACKEND_URL`              | `http://localhost:8010` |
| `INTERNAL_AUTH_TOKEN_TTL_SECONDS` | `60`                    |
| `PYTHON_API_TIMEOUT_MS`           | `60000`                 |

The backend URL must be absolute HTTP(S) without credentials, the secret must
contain at least 32 characters, token TTL must be 10–300 seconds, and timeout
must be 1000–120000 milliseconds. No `NEXT_PUBLIC_` variable participates in
this server-only contract. Docker Compose wires the same development identity
settings to both services and makes Next.js wait for the healthy API.

## Start PostgreSQL and initialize its schema

```powershell
docker compose up db -d
npm run db:bootstrap
npm run seed
```

`db:bootstrap` is for a new, empty database. For an existing database already
on the Alembic revision graph, use `npm run db:migrate` or `npm run db:check`.
The seed is a Python-owned, atomic, idempotent command for application-wide
default categories. Alembic owns schema changes. Files under
`prisma/migrations/` are immutable history and have no executable deployment path.

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

## Temporary HTTPS access outside the local network

Expose only the Next.js port through a development tunnel. Keep FastAPI and
PostgreSQL private. Docker Compose accepts runtime overrides for
`NEXTAUTH_URL` and `NEXTAUTH_SECRET`; set the generated HTTPS tunnel URL and a
fresh random secret before recreating `app`. Cloudflare Quick Tunnels are
temporary development endpoints, so stop the tunnel container after testing
and never reuse the placeholder NextAuth secret for public access.

## Generate Python API types

From the repository root:

```powershell
npm run api:python:generate
npm run api:python:check
```

Generation invokes the backend exporter through `uv`, constructs FastAPI
OpenAPI without a database connection or lifespan startup, and writes the
tracked `src/generated/python-api.ts`. Check mode uses temporary files and
leaves the working tree unchanged.
