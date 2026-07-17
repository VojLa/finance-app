# Alembic migrations

This directory is the active migration history for the Python backend.

## Ownership boundary

The revision graph begins with two no-op revisions:

```text
3d0001base
    ↓
3e0001cutover
```

`3d0001base` represents the physical PostgreSQL schema inherited from the frozen Prisma migration
archive. `3e0001cutover` records the point at which Alembic became the sole migration owner. Neither
revision creates, alters, or drops application objects.

The inherited baseline and ownership marker cannot be downgraded automatically because they record
historical boundaries rather than reversible application schema operations.

## Current policy

- Alembic owns all future production schema changes.
- All 30 application tables and 27 PostgreSQL enums are tracked as `alembic_owned`.
- Prisma migration creation and deployment are disabled.
- The frozen Prisma history is retained only for a restricted historical CI bootstrap.
- Prisma Client remains a runtime compatibility layer.
- `schema.prisma` must be updated when an Alembic revision affects Prisma-visible objects.
- Upgrades are executed by `scripts/database_migrate.py` under a PostgreSQL advisory lock.
- Migrations and stamps are never executed by application startup.

## New revisions

Every future revision must:

1. follow the current single head,
2. declare `prisma_schema_impact` as `required` or `none`,
3. include appropriate SQLAlchemy metadata changes,
4. update `schema.prisma` when the runtime client is affected,
5. include upgrade, rollback or forward-recovery documentation,
6. include integration tests against both an existing and a clean database.

The first schema-changing revision belongs to Step 3F, not to the ownership cutover itself.

See `database/README.md`, `database/cutover/README.md`, and
`database/schema_ownership.toml` for deployment and ownership rules.
