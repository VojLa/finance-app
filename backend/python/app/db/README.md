# SQLAlchemy schema mirror

This package contains the Python backend's runtime database infrastructure and the complete
read-only SQLAlchemy mirror of the Prisma-managed PostgreSQL schema.

## Runtime

- `connection.py` creates one async SQLAlchemy engine and `async_sessionmaker`.
- FastAPI requests receive a request-scoped `AsyncSession`.
- `health.py` checks PostgreSQL connectivity through the SQLAlchemy engine.
- `url.py` converts Prisma-style PostgreSQL URLs to the `postgresql+asyncpg` dialect.

FastAPI startup never runs Alembic commands, stamps revisions, or changes the physical
schema.

## Mirrored schema

The metadata mirror contains all 30 application tables and all 27 PostgreSQL enum types.
Models are split by domain under `models/` and preserve:

- physical Prisma table and column names,
- PostgreSQL data types and numeric precision,
- nullability and server defaults,
- primary keys and foreign keys,
- unique constraints and indexes,
- enum names, values, and ordering.

The mappings reuse existing PostgreSQL enum types with `create_type=False`. ORM relationships
are intentionally not introduced, so repository queries remain explicit and cannot trigger
hidden async lazy loads.

## Parity verification

`../../scripts/sqlalchemy_schema.py` compares `Base.metadata` with SQLAlchemy reflection of a
PostgreSQL database created by the committed Prisma migrations.

```bash
python scripts/sqlalchemy_schema.py --print
python scripts/sqlalchemy_schema.py --check
```

The checker covers columns, types, nullability, defaults, primary keys, foreign keys,
`ON DELETE`, unique constraints, indexes, and enum labels. `_prisma_migrations` and
`alembic_version` are excluded because they belong to migration systems rather than the
application schema.

## Ownership boundary

Prisma remains the only migration owner. Complete SQLAlchemy metadata is a runtime and
verification mirror, not a schema creation mechanism.

Do not call:

```python
Base.metadata.create_all(...)
Base.metadata.drop_all(...)
```

Alembic configuration and the no-op baseline live at the backend root. They establish
baseline readiness only; no application table or enum becomes Alembic-owned until the
separate step 3E cutover is explicitly approved.
