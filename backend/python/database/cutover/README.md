# Alembic ownership cutover

Step 3E-B transfers migration ownership from Prisma to Alembic. This repository currently has no
persistent staging or production database, so the cutover can complete directly without creating
fabricated environment receipts.

## Environment inventory

`environments.toml` records:

- `remote_databases_exist = false`,
- zero required target environments,
- the explicit reason that the application has not yet been deployed to persistent infrastructure.

This declaration is enforced by `scripts/migration_policy.py`. If a persistent environment is
created later, it must be added to the inventory and deployed only through the Alembic runner.

## Completed ownership state

- Alembic is the sole migration owner.
- Revision `3d0001base` represents the inherited Prisma-created schema.
- Revision `3e0001cutover` records the ownership boundary and performs no application DDL.
- All 30 application tables and 27 PostgreSQL enums inherit `alembic_owned` status.
- The Prisma migration history remains a frozen read-only archive.
- Prisma runtime, schema, generator, and deployment tooling have been removed.
- The historical Prisma SQL directory remains only as an immutable hash-verified archive.

## Active commands

From the repository root:

```bash
npm run db:check
npm run db:migrate
npm run db:deploy
npm run db:bootstrap
```

`db:migrate` and `db:deploy` both invoke `scripts/database_migrate.py upgrade` through the locked
Python environment. Upgrades are serialized with a PostgreSQL advisory lock and finish with head,
canonical baseline, and SQLAlchemy parity checks.

`db:bootstrap` is only for an empty PostgreSQL `public` schema. It loads the committed canonical SQL
baseline, stamps `3d0001base`, upgrades to `3e0001cutover`, and verifies the final state.

## Frozen Prisma archive

The old Prisma migration history is retained solely as audit evidence. Python
policy verifies its aggregate hash with `npm run db:archive:verify`. It is not
an executable reconstruction or deployment path; clean databases use
`db:bootstrap` and the canonical baseline plus Alembic revisions.

## Runtime safety

Migrations must not run from:

- FastAPI startup or lifespan,
- Next.js startup,
- background worker startup,
- module import side effects,
- multiple parallel deployment instances.

A deployment runs the database migration job first, then deploys backend, frontend, and workers.

## Future persistent databases

The first persistent database must be created with:

```bash
npm run db:bootstrap
```

Existing externally supplied databases must pass canonical baseline and SQLAlchemy parity checks,
be explicitly stamped at `3d0001base`, and then be upgraded through the Alembic runner. Credentials,
connection strings, personal data, and financial data must never be committed to this directory.

All later schema changes are single-head Alembic revisions with SQLAlchemy
metadata, revision artifacts, upgrade/rollback policy, and PostgreSQL tests.
