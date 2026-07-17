# SQLAlchemy database metadata

This package contains the Python backend's runtime database infrastructure and the complete
SQLAlchemy representation of the PostgreSQL application schema.

## Runtime

- `connection.py` creates one async SQLAlchemy engine and `async_sessionmaker`.
- FastAPI requests receive a request-scoped `AsyncSession`.
- `health.py` checks PostgreSQL connectivity through the SQLAlchemy engine.
- `url.py` converts Prisma-style PostgreSQL URLs to the `postgresql+asyncpg` dialect.

FastAPI startup never runs Alembic commands, stamps revisions, or changes the physical schema.

## Schema metadata

The metadata contains all 30 application tables and all 27 PostgreSQL enum types. Models are split
by domain under `models/` and preserve:

- physical table and column names,
- PostgreSQL data types and numeric precision,
- nullability and server defaults,
- primary keys and foreign keys,
- unique constraints and indexes,
- enum names, values, and ordering.

The mappings reuse existing PostgreSQL enum types with `create_type=False`. ORM relationships are
intentionally not introduced, so repository queries remain explicit and cannot trigger hidden async
lazy loads.

## Parity verification

`../../scripts/sqlalchemy_schema.py` compares `Base.metadata` with SQLAlchemy reflection of a live
PostgreSQL database.

```bash
python scripts/sqlalchemy_schema.py --print
python scripts/sqlalchemy_schema.py --check
```

The checker covers columns, types, nullability, defaults, primary keys, foreign keys, `ON DELETE`,
unique constraints, indexes, and enum labels. `_prisma_migrations` and `alembic_version` are excluded
because they belong to migration systems rather than the application schema.

## Ownership boundary

Alembic is the sole migration owner after revision `3e0001cutover`. SQLAlchemy metadata is the
primary Python schema representation used for Alembic comparison and runtime persistence.

Prisma Client remains enabled for the Next.js runtime, but `schema.prisma` is a compatibility mirror
rather than the migration source of truth.

Do not call:

```python
Base.metadata.create_all(...)
Base.metadata.drop_all(...)
```

All schema changes must be expressed as reviewed Alembic revisions and executed by the dedicated
migration runner, never by application startup.
