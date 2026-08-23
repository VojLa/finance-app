# Persistence, migrations, and runtime

## Scope and source of truth

PostgreSQL is the persistence authority. SQLAlchemy maps the runtime schema;
Alembic alone owns executable application migrations. Shared configuration,
request context, safe serialization, and logging are technical infrastructure,
not a business module.

## Main locations

- Runtime: `backend/python/app/main.py`, `app/lifespan.py`,
  `app/config/settings.py`, `app/shared/`.
- Database: `app/db/{base,connection,health,url,models}/`.
- Migrations: `backend/python/migrations/` and
  `backend/python/database/` schema ownership/revision artifacts.
- Tools: `scripts/database_migrate.py`, `database_schema.py`,
  `sqlalchemy_schema.py`, and `migration_policy.py`.

## Lifecycle and ownership rules

Application startup opens runtime resources only; it never creates schema,
stamps, upgrades, or executes DDL. A schema change must have an Alembic
revision, matching SQLAlchemy mapping, checked schema artifact, and relevant
parity/migration tests. Historical Prisma SQL is archive-only and is not edited
or executed by runtime code.

Shared utilities may hold logging, settings, technical errors, request context,
and numeric serialization. A helper with domain meaning belongs in its domain,
not in `shared`.

## Verification and related material

Run the smallest applicable database check first, then schema/migration parity
for relevant changes. Tests include `test_database_*`, `test_sqlalchemy_*`,
`test_alembic_*`, `test_migration_policy.py`, `test_settings.py`, `test_errors.py`,
and migration integration suites. Read
[database README](../../backend/python/database/README.md) and
[decision 0003](../05-decisions/0003-database-schema-ownership.md).
