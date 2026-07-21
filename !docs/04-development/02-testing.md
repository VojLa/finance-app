# Testing

Run the smallest relevant test first, then the applicable quality gate.

## Python backend

From `backend/python`:

```powershell
uv run pytest tests/test_import_parsing.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run python scripts/check.py
```

`scripts/check.py` runs Ruff, formatting, mypy, and pytest with branch coverage.
The configured coverage floor is 70%. Tests cover application setup, request
handling, auth token validation, account authorization and lifecycle,
invitations, import stages, portfolio reads, database schema parity, and the
migration runner.

Integration and schema-parity tests require PostgreSQL and `DATABASE_URL`.
Schema changes additionally need the migration checks described in
[`backend/python/database/README.md`](../../backend/python/database/README.md).

## Other layers

From the repository root:

```powershell
npx.cmd tsc --noEmit
npm.cmd test
npm.cmd run lint
```

For the Rust prototype:

```powershell
Set-Location backend/rust
cargo test
```

Do not use a passing unit suite to claim import-to-ledger or snapshot correctness:
those workflows are not implemented in Python yet. Add fixture regression tests
for parser changes and contract/OpenAPI coverage for API changes.
