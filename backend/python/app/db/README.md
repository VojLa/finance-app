# SQLAlchemy persistence foundation

This package contains the Python backend's runtime database infrastructure and read-only
SQLAlchemy mirror of the first Prisma persistence slice.

## Runtime

- `connection.py` creates one async SQLAlchemy engine and `async_sessionmaker`.
- FastAPI requests receive a request-scoped `AsyncSession`.
- `health.py` checks PostgreSQL connectivity through the SQLAlchemy engine.
- `url.py` converts Prisma-style PostgreSQL URLs to the `postgresql+asyncpg` dialect.

## Mirrored schema

The first read-only mirror contains:

- `User`
- `Account`
- `AccountMember`
- `Asset`
- `AssetListing`
- `Holding`
- `ExchangeRate`

The mappings use the existing PostgreSQL enum types and preserve Prisma column names,
nullability, numeric precision, and foreign keys. ORM relationships are intentionally not
introduced in this step, so repository queries remain explicit and do not trigger hidden
async lazy loads.

## Ownership boundary

Prisma remains the only migration owner. SQLAlchemy metadata is a runtime mapping, not a
schema creation mechanism.

Do not call:

```python
Base.metadata.create_all(...)
Base.metadata.drop_all(...)
```

This package does not contain Alembic configuration or revisions. A future ownership
cutover requires its own baseline, verification, and explicit approval.
