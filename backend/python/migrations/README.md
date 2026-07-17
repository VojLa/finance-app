# Alembic migrations

This directory contains the future Python-owned migration history.

The first revision is a no-op baseline for the physical PostgreSQL schema that already exists
through the frozen Prisma migration archive. It does not create, alter, or drop application
objects. Existing databases must pass the guarded baseline verification before they are
stamped.

During step 3E-A:

- Prisma remains the current owner of all application tables and enums.
- creation of new Prisma migrations is frozen,
- Alembic is configured and verified, but owns no application object,
- the prepared migration runner requires an explicit baseline stamp for existing databases,
- upgrades are serialized with a PostgreSQL advisory lock,
- `alembic stamp` is an explicit operator action and is never run by application startup,
- the baseline downgrade remains unsupported because Alembic did not create the inherited
  schema,
- Alembic comparison metadata normalizes the default `public` schema, Prisma object names, and
  PostgreSQL unique-index representation without changing runtime SQLAlchemy metadata or
  issuing DDL.

No cutover marker or schema-changing revision belongs in step 3E-A. The ownership activation
revision will be introduced only after all target databases have verified cutover receipts.

See `database/README.md`, `database/cutover/README.md`, and
`database/schema_ownership.toml` for the ownership state and cutover rules.
