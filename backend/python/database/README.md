# Database schema ownership

This directory records the physical PostgreSQL schema and the completed migration ownership
transfer from Prisma to SQLAlchemy and Alembic.

The governing decision is ADR 0006 in `!planning/decisions`.

## Current state

- current migration owner: Alembic
- target migration owner: Alembic
- cutover status: completed
- SQLAlchemy mirror: complete for all 30 application tables and 27 PostgreSQL enum types
- Alembic revision graph: inherited baseline `3d0001base` followed by ownership marker
  `3e0001cutover`
- active deployment runner: `scripts/database_migrate.py`
- Prisma migration history: frozen read-only archive
- Prisma Client: enabled as a Next.js runtime compatibility layer
- persistent staging or production databases: none at the time of cutover

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
        environments.toml
        receipt.template.toml
```

`baseline/schema.sql` represents the PostgreSQL 16 schema created by the final frozen Prisma
migration history. `_prisma_migrations` and `alembic_version` are excluded because they are
migration-system metadata rather than application schema objects.

`prisma_migration_archive.toml` records a deterministic aggregate SHA-256 over every frozen Prisma
migration file. Existing files must never be rewritten and no new Prisma migration may be added.

`schema_ownership.toml` records ownership for tables and PostgreSQL enums. Indexes, unique
constraints, foreign keys, and other child objects inherit the ownership of their table.

`cutover/environments.toml` explicitly records that no persistent remote database existed when the
ownership transfer completed. The repository therefore does not contain fabricated staging or
production receipts.

## Ownership states

- `prisma_owned`: historical state before cutover
- `mirrored_in_sqlalchemy`: SQLAlchemy mapping exists without migration ownership
- `alembic_owned`: Alembic is the only system allowed to change the object
- `retired`: object is no longer part of the active application schema

All application tables and enums now inherit `alembic_owned` from the manifest defaults.

## Active migration commands

From the repository root:

```bash
npm run db:check
npm run db:migrate
npm run db:deploy
npm run db:bootstrap
```

`db:migrate` and `db:deploy` both invoke the Alembic runner. The runner:

- rejects unstamped existing databases,
- rejects unknown revisions,
- requires a single revision head,
- serializes upgrades with a PostgreSQL advisory lock,
- verifies the canonical baseline and SQLAlchemy parity,
- emits a sanitized migration audit without exposing credentials,
- never runs from FastAPI or Next.js startup.

For a new empty PostgreSQL database:

```bash
npm run db:bootstrap
```

Bootstrap loads the canonical baseline, stamps `3d0001base`, upgrades to `3e0001cutover`, and
verifies the result. It refuses a non-empty `public` schema.

## Frozen Prisma archive

The Prisma migration archive exists only for historical CI verification. Its restricted wrapper is:

```bash
CI=true ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY=1 npm run db:prisma:archive:verify
```

The wrapper checks that the target schema is empty before calling Prisma Migrate. No normal
production or developer deployment command may invoke Prisma Migrate.

Prisma Client, `prisma validate`, `prisma generate`, and Prisma Studio remain available. The Prisma
schema is a runtime compatibility mirror, not the migration source of truth.

## SQLAlchemy metadata parity

The complete SQLAlchemy mirror covers:

- 30 application tables,
- 27 PostgreSQL enum types,
- columns, names, types, nullability, and server defaults,
- primary keys, foreign keys, and delete behavior,
- unique constraints and indexes,
- enum values and ordering.

Run:

```bash
cd backend/python
python scripts/sqlalchemy_schema.py --check
```

The parity checker performs no schema DDL.

## Alembic ownership boundary

The revision `3d0001base` is a no-op marker for the inherited Prisma schema. The revision
`3e0001cutover` is a second no-op marker recording Alembic ownership. Their downgrades are blocked
because neither revision created the inherited application schema.

An externally supplied existing database must first pass:

```bash
python scripts/database_schema.py --check
python scripts/sqlalchemy_schema.py --check
python scripts/alembic_baseline.py --verify
```

It must then be explicitly stamped at `3d0001base` and upgraded through
`database_migrate.py upgrade`. Automatic stamping is prohibited.

## Future schema changes

Every production schema change after this cutover must be an Alembic revision. A revision must
update SQLAlchemy metadata and must update `schema.prisma` when Prisma Client-visible objects are
affected. The frozen Prisma migration directory and canonical inherited baseline must not be
rewritten to represent later changes.

The next database milestone is Step 3F: the first real Alembic-owned schema migration.

## Canonical baseline maintenance

The canonical baseline remains a verification artifact for the inherited starting schema. CI uses
`--check` and fails if that inherited schema or checksum changes unexpectedly. It is not regenerated
for ordinary post-cutover Alembic revisions.

## First Alembic-owned schema change

Revision `3f0001acctnote` adds nullable `Account.notes` as the first physical schema change owned by Alembic. The inherited baseline remains immutable; the current head is verified through `database/schema_revisions.toml` and the revision-specific schema artifact.
