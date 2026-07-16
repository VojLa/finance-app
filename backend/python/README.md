# Python Backend

Target role:

- FastAPI HTTP APIs.
- Import orchestration and validation workflows.
- Background job entry points.
- Provider integrations for prices, FX, imports, and external services.
- Calls into Rust engines for expensive deterministic calculations.

Run locally:

```powershell
cd backend/python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload --port 8010
```

Run with Docker from the repository root:

```powershell
docker compose up api --build
```

First read-only portfolio endpoint:

```text
GET /portfolio?user_id=<user-id>&account_id=<optional-account-id>
```

`user_id` is a temporary migration parameter until auth/session sharing between Next.js and
FastAPI is designed.

Tests:

```powershell
cd backend/python
pytest
```

Parity check against the current Next.js endpoint:

```powershell
$env:PARITY_USER_ID="<user-id>"
$env:NEXT_SESSION_COOKIE="<next-auth cookie from browser>"
npm run api:compare:portfolio -- --account-id <optional-account-id>
```

The Next endpoint still uses NextAuth, so the parity script needs a valid session cookie
until shared auth between Next.js and FastAPI is designed.
