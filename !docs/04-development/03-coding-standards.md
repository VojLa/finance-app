# Coding Standards

- Keep React components and Next.js routes free of financial business rules.
  Current legacy routes are migration debt, not a model for new work.
- In Python, routers validate transport concerns and delegate to module services;
  repositories keep SQL explicit. `main.py` only assembles the application.
- Enforce account isolation in the backend. Never rely on hidden frontend state
  or an account id supplied by the browser without membership verification.
- Use `Decimal` and explicit currency/rounding rules for monetary calculations.
  Do not introduce new `float`-based financial logic or hard-code CZK for
  account snapshots.
- Treat imports and providers as untrusted. Preserve unsupported rows as review
  issues, validate content before persistence, and never log raw financial data.
- Make write transactions, idempotency, and concurrency boundaries explicit.
  In particular, multi-file import post-processing must run once per
  source/account batch when that workflow is added.
- SQLAlchemy metadata is runtime representation; Alembic is the only migration
  owner. Do not call `create_all`, alter historical Prisma migrations, or run
  migrations from application startup.
- Update `schema.prisma` as a compatibility mirror when an Alembic migration
  changes Prisma Client-visible objects. Do not create a new Prisma migration.
- Keep Rust engines pure, explicit, and behind a Python-owned interface. The
  current crate is experimental and does not authorize float arithmetic in the
  production finance path.
- Pair behavior changes with focused tests and update these implementation docs
  when a module boundary, API contract, data flow, or operational procedure changes.
