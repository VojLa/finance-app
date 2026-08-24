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
