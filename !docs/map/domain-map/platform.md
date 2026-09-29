# Platform map

Type: domain-map
Status: current
Owns: L1 routing for persistence, shared runtime and frontend platform
Code: shared Python runtime, database, Next.js shell, tooling and Rust experiment
Update when: platform ownership, entry point or dependency changes

ID: `DOM-PLATFORM`
Purpose: persistence, shared runtime, adapters and generated contracts
Source of truth: PostgreSQL, SQLAlchemy, Alembic and FastAPI OpenAPI

- Entry points: app factory, lifespan, API router and schema tooling.
- Modules: `app/db/`, `app/config/`, `app/shared/`, Next.js adapters.
- Depends on: no business domain authority.
- Used by: all runtime domains.
- Data: [ownership](../../data/README.md).
- Tests: [domain test matrix](../../domains/platform/testing.md).
- Details: [domain README](../../domains/platform/README.md) and [modules](../../domains/platform/modules.md).
