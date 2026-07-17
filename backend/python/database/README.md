# Database schema ownership

This directory records the physical PostgreSQL schema during the controlled migration from
Prisma to SQLAlchemy and Alembic.

The governing decision is ADR 0006 in `!planning/decisions`. Prisma remains the migration
owner until the explicit activation PR in step 3E-B. A complete SQLAlchemy mirror, an Alembic
baseline, or a prepared deployment runner does not transfer ownership by itself.

## Current state

- current migration owner: Prisma
- target migration owner: Alembic
- cutover status: ready, not activated
- production schema changes: no new Prisma migrations may be created
- frozen Prisma history: retained for legacy bootstrap verification
- SQLAlchemy mirror: complete for all 30 application tables and 27 enum types
- Alembic revision graph: one verified no-op baseline revision
- prepared Alembic runner: check, upgrade, and empty-database bootstrap
- Alembic application-object ownership: none
- Prisma Client: still enabled as a Next.js runtime compatibility layer

## Files

```text
database/
    README.md
    schema_ownership.toml
    prisma_migration_archive.toml
    baseline/
        schema.sql
        schema.sha256
    cutover/
        README.md
        receipt.template.toml
```

`baseline/schema.sql` is generated from a clean PostgreSQL 16 database after applying all
committed Prisma migrations. It is not handwritten. `_prisma_migrations` and
`alembic_version` are excluded because they are migration-system metadata rather than
application schema objects.

`prisma_migration_archive.toml` records a deterministic aggregate SHA-256 over every file in
the frozen Prisma migration directory. The hash input is the sorted relative path, a NUL
separator, the file-content SHA-256, and a second NUL separator.

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
still modify it. During step 3E-A all 30 tables and all 27 enum types remain Prisma-owned.

## Cutover rules

1. Start from a schema produced by the frozen Prisma migration archive.
2. Keep the canonical baseline and ownership manifest synchronized with that schema.
3. Verify complete SQLAlchemy metadata parity.
4. Verify and explicitly stamp every target database at `3d0001base`.
5. Record a non-secret receipt for every target environment.
6. Activate Alembic ownership only in the separate step 3E-B PR.
7. After activation, create new production schema changes only in Alembic.
8. Never rewrite the frozen Prisma migration history.

## Frozen Prisma migration policy

Run from `backend/python`:

```bash
python scripts/migration_policy.py --check
```

The policy check verifies:

- the frozen archive file count, migration count, final migration, and aggregate hash,
- the ownership manifest state,
- a single-head Alembic revision graph,
- the fail-closed Prisma migration creation command,
- the prepared Alembic root commands,
- the absence of runtime DDL and automatic startup migrations,
- the absence of raw Prisma migration commands in deployment workflows.

The root `db:migrate` command intentionally fails. The existing `db:deploy` alias remains
unchanged only until the activation PR. CI uses the explicitly named
`db:prisma:deploy:legacy` command solely to verify the frozen historical bootstrap path.

Prisma Client, `prisma validate`, `prisma generate`, and Prisma Studio remain available. The
Prisma schema is a runtime compatibility mirror, not the future migration source of truth.

## SQLAlchemy metadata parity

The complete SQLAlchemy mirror covers:

- 30 application tables,
- 27 PostgreSQL enum types,
- columns and physical names,
- data types, nullability, and server defaults,
- primary keys, foreign keys, and `ON DELETE` behavior,
- unique constraints and indexes,
- enum values and ordering.

Run:

```bash
python scripts/sqlalchemy_schema.py --check
```

For diagnostics without connecting to PostgreSQL:

```bash
python scripts/sqlalchemy_schema.py --print
```

The parity checker performs no schema DDL.

## Alembic baseline and prepared runner

The revision `3d0001base` is a no-op marker for the inherited Prisma schema. Its upgrade does
not create or alter application objects, and its downgrade is intentionally blocked because
Alembic did not create the schema.

Before stamping an existing database:

```bash
python scripts/database_schema.py --check
python scripts/sqlalchemy_schema.py --check
python scripts/alembic_baseline.py --verify
```

Only after those checks pass may an operator explicitly run:

```bash
alembic stamp 3d0001base
python scripts/database_migrate.py check
python scripts/database_migrate.py upgrade
```

The prepared runner:

- rejects unstamped existing databases,
- rejects unknown Alembic revisions,
- requires a single revision head,
- serializes upgrade execution with a PostgreSQL advisory lock,
- verifies schema parity after upgrading,
- never runs from FastAPI or Next.js startup.

For a new empty PostgreSQL database:

```bash
python scripts/database_migrate.py bootstrap
```

Bootstrap refuses a non-empty `public` schema. It loads the canonical SQL baseline, stamps the
baseline revision, upgrades to head, and verifies the final state.

## Environment receipts

Every staging and production database must complete the procedure in `cutover/README.md` and
produce a receipt based on `cutover/receipt.template.toml` before step 3E-B may activate
Alembic ownership.

Receipts must not contain passwords, connection strings, personal data, or financial data.

## Runtime persistence slice

The portfolio read path currently uses `Account`, `AccountMember`, `Holding`, and
`ExchangeRate`, with transitive mappings for `User`, `Asset`, `AssetListing`, and their enum
types. The remaining SQLAlchemy mappings establish metadata parity and do not introduce new
application reads or writes by themselves.

## Generate or verify the canonical baseline

Requirements:

- a PostgreSQL database with the frozen Prisma migration archive applied,
- PostgreSQL 16 `pg_dump` available on `PATH`,
- `DATABASE_URL` pointing to that database.

From `backend/python`:

```bash
python scripts/database_schema.py --write
python scripts/database_schema.py --check
```

`--write` is an explicit maintenance command. CI uses `--check` and fails when the live
schema differs from the committed baseline or when the checksum is invalid.
