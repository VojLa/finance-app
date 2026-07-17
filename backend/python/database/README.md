# Database schema ownership

This directory records the physical PostgreSQL schema during the hybrid migration from
Prisma to SQLAlchemy and Alembic.

The governing decision is ADR 0006 in `!planning/decisions`. Prisma remains the migration
owner until an explicit cutover is approved. Adding SQLAlchemy mappings does not transfer
migration ownership by itself.

## Current state

- current migration owner: Prisma
- target migration owner: Alembic
- cutover status: not started
- production schema changes: still created by Prisma migrations
- SQLAlchemy models: not introduced by this inventory step
- Alembic revisions: not introduced by this inventory step

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
committed Prisma migrations. It is not handwritten. `_prisma_migrations` is excluded
because it is migration-system metadata rather than an application schema object.

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
3. Add SQLAlchemy mappings without changing migration ownership.
4. Verify the future Alembic baseline on both a clean database and a copy of an existing
   database.
5. Record the cutover commit and affected objects explicitly.
6. After cutover, create new production schema changes only in Alembic.
7. Never rewrite existing Prisma migration history merely to make the baseline cleaner.

## First Python persistence slice

The current portfolio read model directly queries:

- `Account`
- `AccountMember`
- `Holding`
- `ExchangeRate`

Its first SQLAlchemy mapping slice will also require these transitive dependencies:

- `User`
- `Asset`
- `AssetListing`
- `AccountType`
- `AccountMemberRole`
- `AccountRelationType`
- `AssetType`
- `PriceSource`
- `ExchangeRateSource`

These objects remain `prisma_owned` during step 3A. The inventory only records their
current Python usage so that step 3B can introduce mappings without an accidental schema
cutover.

## Generate or verify the baseline

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
