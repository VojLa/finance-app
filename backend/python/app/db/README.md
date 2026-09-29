# SQLAlchemy database metadata

This package contains the Python backend's runtime database infrastructure and the complete
SQLAlchemy representation of the PostgreSQL application schema.

## Runtime

- `connection.py` creates one async SQLAlchemy engine and `async_sessionmaker`.
- FastAPI requests receive a request-scoped `AsyncSession`.
- `health.py` checks PostgreSQL connectivity through the SQLAlchemy engine.
- `url.py` normalizes PostgreSQL URLs to the `postgresql+asyncpg` dialect.

FastAPI startup never runs Alembic commands, stamps revisions, or changes the physical schema.

## Schema metadata

The metadata contains all 38 application tables and all 30 PostgreSQL enum types. Models are split
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

Prisma runtime and schema tooling are absent. The historical SQL migration
archive is not a runtime schema representation or executable migration path.

Do not call:

```python
Base.metadata.create_all(...)
Base.metadata.drop_all(...)
```

All schema changes must be expressed as reviewed Alembic revisions and executed by the dedicated
migration runner, never by application startup.

## First Alembic-owned schema change

Revision `3f0001acctnote` adds nullable `Account.notes` as the first physical schema change owned by Alembic. The inherited baseline remains immutable; the current head is verified through `database/schema_revisions.toml` and the revision-specific schema artifact.

Revision `3g0001liabbal` adds the explicit `LiabilityBalance` model and
dedicated source enum. The model mirrors canonical MONEY and TIMESTAMP types,
component checks, account foreign key, uniqueness, and lookup index.

Revision `3h0001twdata` adds the explicit `twelve_data` identity to the
`AssetAliasProvider` and `PriceSource` enums. It mirrors provider ownership
without registering an HTTP adapter.

Revisions `3i0001d1base` and `3j0001twfx` add daily lineage tables and the
direct Twelve Data FX source identity. Revision `3j0001twfx` is historical;
the current head is `3o0001unkbasis`, after the multi-currency holding
cost-basis (`3k0001mcost`), durable background-job (`3l0001bgjob`), and import
publication-anchor (`3m0001importanchor`) revisions. The head initializes an
exact revision-zero Holding watermark for newly created investment accounts and
safely backfills only provably empty existing accounts. Revision `3o0001unkbasis`
allows an investment position and snapshot to retain exact quantity and market
value when acquisition cost evidence is unavailable; its cost-basis and dependent
profit metrics remain `NULL` rather than being coerced to zero.
