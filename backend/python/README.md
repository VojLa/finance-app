# Python Backend

The Python backend is the primary application backend for the migration toward the
`0.1 - Architecture Locked` milestone. It owns FastAPI transport, import orchestration,
financial application services, background job entry points, and provider integrations.

## Requirements

- Python 3.12 or newer
- PostgreSQL for readiness and data-backed endpoints
- Docker Compose when running the full local stack

## Local installation

From `backend/python`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

On Linux or macOS, activate the environment with:

```bash
source .venv/bin/activate
```

## Run locally

```bash
uvicorn app.main:app --reload --port 8010
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

## Tests and linting

From `backend/python`:

```bash
pytest
ruff check .
```

The application tests cover FastAPI creation, root metadata, OpenAPI generation,
liveness, readiness without a database, and readiness with a mocked healthy database.

## Project structure

```text
app/
    api/                 HTTP routing and API version aggregation
    config/              application settings
    db/                  database connection lifecycle and health checks
    modules/             domain-owned application code and API adapters
    lifespan.py          process startup and shutdown resources
    main.py              FastAPI application factory

tests/                   application and API regression tests
```

Rules:

- `main.py` assembles the application but does not contain business logic.
- `api/` is a thin transport layer.
- Domain endpoints belong to their owning module.
- `db/` contains shared database infrastructure, not financial rules.
- New business logic must not be added to Next.js route handlers as its long-term source of truth.

## Portfolio parity check

The current Next.js endpoint still uses NextAuth. Until shared authentication exists, the
parity script requires a valid browser session cookie:

```powershell
$env:PARITY_USER_ID="<user-id>"
$env:NEXT_SESSION_COOKIE="<next-auth cookie from browser>"
npm run api:compare:portfolio -- --account-id <optional-account-id>
```
