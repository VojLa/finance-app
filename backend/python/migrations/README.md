# Alembic migrations

This directory contains the future Python-owned migration history.

The first revision is a no-op baseline for the physical PostgreSQL schema that already
exists through the committed Prisma migrations. It does not create, alter, or drop
application objects. Existing databases must pass the guarded baseline verification before
they are stamped.

During step 3D:

- Prisma remains the sole owner of production schema changes.
- Alembic is configured and verified, but owns no application table or enum.
- `alembic stamp` is an explicit operator action and is never run by FastAPI startup.
- The baseline downgrade is intentionally unsupported because Alembic did not create the
  inherited schema.
- Alembic comparison metadata normalizes the default `public` schema, Prisma object names,
  and PostgreSQL unique-index representation without changing runtime SQLAlchemy metadata or
  issuing DDL.

See `database/README.md` and `database/schema_ownership.toml` for the ownership state and
cutover rules.
