# Migrations and schema recovery

Type: runbook
Status: current
Owns: safe schema verification and migration recovery route
Code: `backend/python/scripts/database_migrate.py`, `database_schema.py`
Update when: migration process, schema revision artifact or recovery rule changes

Inspect the ownership manifest before a schema change. Add a reviewed Alembic
revision with SQLAlchemy parity and a revision schema artifact. Never migrate in
application startup. Drift, ambiguous state or invalid artifacts stop the
operation; do not stamp or repair by guessing.

From the repository root use `npm.cmd run db:check` before upgrade and
`npm.cmd run db:deploy` to apply the graph. From `backend/python`, targeted checks are:

```powershell
uv run python scripts/migration_policy.py --check
uv run alembic -c alembic.ini current --check-heads
uv run alembic -c alembic.ini check
uv run python scripts/database_schema.py --check --revision 3s0001manualbaseline
uv run python scripts/sqlalchemy_schema.py --check
```

The current worktree head is `3s0001manualbaseline`. Checks require PostgreSQL 16 tooling
and an explicit `DATABASE_URL`. Clean bootstrap, inherited baseline, schema artifact,
seed and parity behavior are owned by `database-schema.yml`. Stop on multiple heads,
checksum drift, model/schema mismatch or an unexpected database target.
