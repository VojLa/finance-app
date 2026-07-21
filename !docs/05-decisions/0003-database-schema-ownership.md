# 0003 Alembic owns database schema changes

## Status

Accepted and implemented.

## Decision

SQLAlchemy and Alembic are the sole owners of PostgreSQL schema changes. The
cutover completed with inherited baseline revision `3d0001base`, ownership
marker `3e0001cutover`, and current first Alembic-owned schema change
`3f0001acctnote`.

## Consequences

- The complete SQLAlchemy metadata mirrors 30 application tables and 27
  PostgreSQL enum types.
- The canonical Prisma-created baseline is immutable verification evidence.
- Prisma Client and `schema.prisma` remain for Next.js runtime compatibility,
  but the Prisma migration history is frozen and no normal environment may apply
  it.
- A new schema change requires a reviewed Alembic revision, matching SQLAlchemy
  metadata, migration-runner and parity checks, and a Prisma schema update when
  Prisma Client consumes the changed object.
- FastAPI and Next.js startup must never run DDL, stamp revisions, or upgrade a
  database. Deployment uses the dedicated `database_migrate.py` runner, which
  takes a PostgreSQL advisory lock and verifies the expected schema.

The operational procedure and ownership inventory are in
[`backend/python/database`](../../backend/python/database/README.md).
