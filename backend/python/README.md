# Python Backend

The Python backend is the primary application backend for the
`0.1 - Architecture Locked` milestone. It owns FastAPI transport, financial
application services, import orchestration, background job entry points, and provider
integrations.

Architectural decisions and milestone scope are documented in [`!planning`](../../!planning).

## Requirements

- Python `3.12.10` (declared in [`.python-version`](./.python-version))
- [`uv`](https://docs.astral.sh/uv/) for the primary development workflow
- PostgreSQL for readiness and data-backed endpoints
- Docker Compose for the full local stack

## Install dependencies

From `backend/python`:

```bash
uv sync --frozen --extra dev
```

### Windows recovery bootstrap

The PowerShell bootstrap recreates `.venv`, discovers Python 3.12, and installs the
backend with development dependencies:

```powershell
cd backend/python
.\bootstrap.ps1
.\bootstrap.ps1 -RunChecks
```

An explicit interpreter can be supplied when discovery is not sufficient:

```powershell
.\bootstrap.ps1 -PythonPath "C:\path\to\python.exe" -RunChecks
```

## Run locally

```bash
uv run uvicorn app.main:app --reload --port 8010
```

The application is available at `http://localhost:8010`.

Important endpoints:

```text
GET /api/v1/health/live
GET /api/v1/health/ready
GET /api/v1/portfolio?user_id=<user-id>&account_id=<optional-account-id>
GET /docs
GET /openapi.json
```

The original `/health` and `/portfolio` paths remain temporary compatibility aliases.
New clients should use `/api/v1`.

`user_id` remains a temporary migration parameter until auth and session sharing between
Next.js and FastAPI is implemented.

## Run with Docker

From the repository root:

```bash
docker compose up api --build
```

To start the database, frontend, and backend together:

```bash
docker compose up --build
```

The API container uses `/api/v1/health/live` as its Docker healthcheck. The readiness
endpoint additionally verifies PostgreSQL connectivity.

## Development checks

Run the complete backend quality gate:

```bash
uv run python scripts/check.py
```

The command runs, in order:

1. Ruff linting
2. Ruff formatting check
3. mypy type checking
4. pytest with branch coverage

Individual commands:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
```

The initial coverage threshold is 70 percent. The threshold should increase as domain
modules replace migration code.

## Database schema inventory

Prisma remains the only migration owner during the hybrid migration. The target owner is
Alembic, but SQLAlchemy mappings or Alembic revisions are not introduced by the inventory
step.

The current physical PostgreSQL schema is recorded in:

```text
database/
    README.md
    schema_ownership.toml
    baseline/
        schema.sql
        schema.sha256
```

`schema_ownership.toml` inventories all Prisma tables and PostgreSQL enum types and records
the first Python persistence slice. Table-owned indexes, unique constraints, foreign keys,
and checks inherit the ownership of their table.

To regenerate the baseline intentionally after applying all committed Prisma migrations:

```bash
uv run python scripts/database_schema.py --write
```

To compare a migrated PostgreSQL database with the committed baseline:

```bash
uv run python scripts/database_schema.py --check
```

Both commands require `DATABASE_URL` and PostgreSQL 16 `pg_dump`. The drift check excludes
`_prisma_migrations`, because it is migration-system metadata rather than an application
schema object.

The `Database Schema` GitHub Actions workflow creates a clean PostgreSQL 16 database,
applies all committed Prisma migrations, compares the resulting schema with the baseline,
and validates the ownership manifest.

## Environment variables

| Variable       | Default       | Purpose                                |
| -------------- | ------------- | -------------------------------------- |
| `ENVIRONMENT`  | `development` | `development`, `test`, or `production` |
| `DATABASE_URL` | unset         | PostgreSQL connection string           |
| `LOG_LEVEL`    | `INFO`        | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `LOG_JSON`     | `false`       | Emit machine-readable JSON logs        |
| `DOCS_ENABLED` | `true`        | Enable `/docs` and `/openapi.json`     |

Production startup requires:

```text
DATABASE_URL=<configured PostgreSQL URL>
LOG_JSON=true
DOCS_ENABLED=false
ENVIRONMENT=production
```

Invalid production settings stop application startup instead of falling back to unsafe
development defaults.

## API platform conventions

Application errors use a stable envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Resource was not found.",
    "request_id": "9ae1021f-f78c-4bea-a860-c643ae127f55"
  }
}
```

Every request receives an `X-Request-ID` response header. A valid UUID supplied by the
client is propagated; an invalid or missing value is replaced. Structured request logs
include the request ID, method, path, status code, duration, and environment. Request
bodies, cookies, authorization headers, and financial payloads are not logged.

Health endpoints intentionally keep their small orchestration-friendly response format
instead of the application error envelope.

## Continuous integration

`.github/workflows/backend-python.yml` runs when backend files or the workflow itself
change. It installs the locked dependencies with `uv sync --frozen` and runs Ruff, mypy,
and pytest quality checks.

`.github/workflows/database-schema.yml` additionally verifies Prisma migrations, the
canonical PostgreSQL schema baseline, its checksum, and the ownership inventory.

## Project structure

```text
app/
    api/                 HTTP routing and API version aggregation
    config/              validated application settings
    db/                  database connection lifecycle and health checks
    modules/             domain-owned application code and API adapters
    shared/              error, request-context, and logging infrastructure
    lifespan.py          process startup and shutdown resources
    main.py              FastAPI application factory

database/
    baseline/             canonical PostgreSQL schema generated from Prisma migrations
    schema_ownership.toml database object ownership and Python usage inventory

scripts/
    check.py              local quality gate
    database_schema.py    schema baseline generation and drift detection

tests/                   application, API, and schema inventory regression tests
```

Rules:

- `main.py` assembles the application but does not contain business logic.
- `api/` is a thin transport layer.
- Domain endpoints belong to their owning module.
- `db/` contains shared runtime database infrastructure, not financial rules.
- `database/` records physical schema ownership and migration evidence.
- New business logic must not use Next.js route handlers as its long-term source of truth.

## Portfolio parity check

The current Next.js endpoint still uses NextAuth. Until shared authentication exists, the
parity script requires a valid browser session cookie:

```powershell
$env:PARITY_USER_ID="<user-id>"
$env:NEXT_SESSION_COOKIE="<next-auth cookie from browser>"
npm run api:compare:portfolio -- --account-id <optional-account-id>
```
