# 0003 Alembic owns database schema changes

Type: historical
Status: historical
Owns: retained rationale for Alembic schema ownership
Code: migrations, schema artifacts and SQLAlchemy mapping
Update when: the record is superseded or archived

## Status

Accepted and implemented.

## Decision

SQLAlchemy and Alembic are the sole owners of PostgreSQL schema changes. The
cutover completed with inherited baseline revision `3d0001base`, ownership
marker `3e0001cutover`, first Alembic-owned schema change `3f0001acctnote`,
and current head `3p0001rbfoundation`.

## Consequences

- The complete SQLAlchemy metadata mirrors 42 application tables and 30
  PostgreSQL enum types.
- The canonical Prisma-created baseline is immutable verification evidence.
- Prisma Client, `schema.prisma`, its generator, and executable migration tooling
  are removed. Historical Prisma SQL is a frozen hash-verified archive only.
- A new schema change requires a reviewed Alembic revision, matching SQLAlchemy
  metadata, migration-runner, revision schema artifact, and parity checks.
- FastAPI and Next.js startup must never run DDL, stamp revisions, or upgrade a
  database. Deployment uses the dedicated `database_migrate.py` runner, which
  takes a PostgreSQL advisory lock and verifies the expected schema.

The operational procedure and ownership inventory are in
[`backend/python/database`](../../backend/python/database/README.md).
