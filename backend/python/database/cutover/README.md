# Alembic ownership cutover preparation

Step 3E-A prepares the repository and target databases for the later ownership activation in
step 3E-B. It does not transfer migration ownership by itself.

## Repository state

- Prisma remains the current migration owner.
- Alembic remains the target migration owner.
- New Prisma migration creation is frozen.
- Existing Prisma migrations are retained as a read-only historical archive.
- Prisma Client remains enabled as a runtime compatibility layer for the Next.js application.
- `schema.prisma` is not the migration source of truth after activation.
- Production activation remains blocked until every target database has a verified receipt.

## Required database procedure

For every staging or production database:

1. Create and verify a database backup or provider snapshot.
2. Record the application commit and a non-secret database identifier.
3. Run the canonical PostgreSQL baseline check.
4. Run the complete SQLAlchemy live parity check.
5. Run the guarded Alembic baseline verification.
6. Record representative data checksums or row counts.
7. Explicitly stamp revision `3d0001base`.
8. Run `database_migrate.py check`.
9. Run `database_migrate.py upgrade`.
10. Repeat schema parity and data-preservation checks.
11. Complete a cutover receipt based on `receipt.template.toml`.

The stamp operation must never be run by FastAPI startup, Next.js runtime, or multiple
parallel deployment instances.

## Prepared commands

From `backend/python`:

```bash
python scripts/migration_policy.py --check
python scripts/database_migrate.py check
python scripts/database_migrate.py upgrade
python scripts/database_migrate.py bootstrap
```

`bootstrap` is restricted to an empty PostgreSQL `public` schema. It loads the committed
canonical SQL baseline, stamps `3d0001base`, upgrades to the current head, and verifies the
result. It does not support initializing a partially populated database.

## Activation boundary

Step 3E-B may start only after:

- PR 3E-A is merged,
- every target database is stamped and verified,
- every required receipt exists,
- no Prisma or Alembic schema change is in flight,
- the frozen Prisma archive hash still matches,
- Backend Python and Database Schema CI are green.

Step 3E-B will add the explicit ownership marker revision and switch the active deployment
migration command to Alembic.
