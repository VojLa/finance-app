# Data ownership

Type: reference
Status: current
Owns: runtime and migration ownership rules
Code: `schema_ownership.toml`, SQLAlchemy models and Alembic revisions
Update when: a table, enum, model owner or persistence authority changes

- PostgreSQL stores application financial evidence.
- SQLAlchemy completely maps the runtime schema.
- Alembic alone creates and executes application schema migrations.
- `prisma/migrations/` is a frozen historical SQL archive, not a runtime tool.
- Table indexes, constraints and foreign keys inherit the table owner.
- Application startup never runs `create_all`, `drop_all`, stamp or upgrade.

The machine-readable authority is `backend/python/database/schema_ownership.toml`.
