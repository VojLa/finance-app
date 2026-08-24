# Persistence and frontend platform

Type: domain
Status: current
Owns: shared runtime, migrations, adapters and experimental-engine boundary
Code: `app/db/`, `app/shared/`, `app/config/`, `src/app/`, `src/modules/`, Rust
Update when: platform authority, generated contract or runtime integration changes

PostgreSQL, SQLAlchemy and Alembic form the persistence platform. Next.js provides presentation and same-origin adapters; generated API types are transport-only. `backend/rust/finance_engine` is experimental and not financial truth.

Verification: [test matrix](testing.md). Persistence: [data ownership](../../data/README.md).
