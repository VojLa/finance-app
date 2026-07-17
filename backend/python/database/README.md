# Database schema ownership

This directory records the physical PostgreSQL schema during the hybrid migration from
Prisma to SQLAlchemy and Alembic.

The governing decision is ADR 0006 in `!planning/decisions`. Prisma remains the migration
owner until an explicit cutover is approved. Adding SQLAlchemy mappings or an Alembic
baseline does not transfer migration ownership by itself.

## Current state

- current migration owner: Prisma
- target migration owner: Alembic
- cutover status: not started
- production schema changes: still created by Prisma migrations
- SQLAlchemy mirror: complete for all 30 application tables and 27 enum types
- Alembic revision graph: one verified no-op baseline revision
- Alembic application-object ownership: none

## Files

```text
database/
    README.md
    schema_ownership.toml
    baseline/
        schema.sql
        schema.sha256
```

`baseline/schema.sql` is generated from a clean PostgreSQL 16 database after applying all
committed Prisma migrations. It is not handwritten. `_prisma_migrations` and
`alembic_version` are excluded because they are migration-system metadata rather than
application schema objects.

`schema_ownership.toml` records independently migratable application objects. Ownership is
tracked for tables and PostgreSQL enum types. Indexes, unique constraints, foreign keys,
checks, and other table-owned child objects inherit the owner and cutover status of their
table.

## Ownership states

- `prisma_owned`: Prisma is the only system allowed to change the object.
- `mirrored_in_sqlalchemy`: a SQLAlchemy mapping exists, but Prisma still owns migrations.
- `alembic_owned`: Alembic is the only system allowed to change the object.
- `retired`: the object is no longer part of the active application schema.

A table or enum must never be marked `alembic_owned` while an active Prisma migration can
still modify it.

## Cutover rules

1. Start from a schema produced by committed Prisma migrations on a clean database.
2. Keep the generated baseline and ownership manifest synchronized with that schema.
3. Complete SQLAlchemy mappings without changing migration ownership.
4. Verify the Alembic baseline on both a clean database and a copy of an existing database.
5. Record the cutover commit and affected objects explicitly.
6. After cutover, create new production schema changes only in Alembic.
7. Never rewrite existing Prisma migration history merely to make the baseline cleaner.

## SQLAlchemy metadata parity

The complete SQLAlchemy mirror covers every object recorded in the ownership manifest:

- 30 application tables,
- 27 PostgreSQL enum types,
- columns and physical names,
- data types, nullability, and server defaults,
- primary keys, foreign keys, and `ON DELETE` behavior,
- unique constraints and indexes,
- enum values and ordering.

The live parity check reflects a PostgreSQL 16 database created by the committed Prisma
migrations and compares it with `Base.metadata`:

```bash
python scripts/sqlalchemy_schema.py --check
```

For diagnostics without connecting to PostgreSQL:

```bash
python scripts/sqlalchemy_schema.py --print
```

The parity checker performs no schema DDL.

## Alembic baseline readiness

The revision `3d0001base` is a no-op marker for the inherited Prisma schema. Its upgrade does
not create or alter application objects, and its downgrade is intentionally blocked because
Alembic did not create the schema.

Before stamping any database, run:

```bash
python scripts/database_schema.py --check
python scripts/sqlalchemy_schema.py --check
python scripts/alembic_baseline.py --verify
```

Only after all checks pass may an operator run:

```bash
alembic stamp 3d0001base
alembic current --check-heads
alembic check
alembic upgrade head
```

Stamping is never performed by FastAPI startup. It creates only
`public.alembic_version`; application data and physical application objects must remain
unchanged.

### Prisma-free bootstrap verification

A future new database can be initialized without replaying Prisma history:

```bash
createdb finance_app
psql finance_app -c 'DROP SCHEMA public CASCADE'
psql finance_app -f database/baseline/schema.sql
python scripts/alembic_baseline.py --verify
alembic stamp 3d0001base
alembic upgrade head
```

This is a verified readiness path, not the production cutover. Prisma remains the only
migration owner until step 3E is approved.

## Runtime persistence slice

The portfolio read path currently uses:

- `Account`
- `AccountMember`
- `Holding`
- `ExchangeRate`

Its transitive mappings are:

- `User`
- `Asset`
- `AssetListing`
- `AccountType`
- `AccountMemberRole`
- `AccountRelationType`
- `AssetType`
- `PriceSource`
- `ExchangeRateSource`

The remaining SQLAlchemy mappings establish complete metadata parity for future Python
persistence work. They do not introduce new application reads or writes by themselves.

## Generate or verify the canonical baseline

Requirements:

- a PostgreSQL database with all committed Prisma migrations applied
- PostgreSQL 16 `pg_dump` available on `PATH`
- `DATABASE_URL` pointing to that database

From `backend/python`:

```bash
python scripts/database_schema.py --write
python scripts/database_schema.py --check
```

`--write` is an explicit maintenance command. CI uses `--check` and fails when the live
schema differs from the committed baseline or when the checksum is invalid.
