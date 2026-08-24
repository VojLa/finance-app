# Platform map

ID: `DOM-PLATFORM`
Purpose: persistence, shared runtime, adapters and generated contracts
Source of truth: PostgreSQL, SQLAlchemy, Alembic and FastAPI OpenAPI

- Entry points: app factory, lifespan, API router and schema tooling.
- Modules: `app/db/`, `app/config/`, `app/shared/`, Next.js adapters.
- Depends on: no business domain authority.
- Used by: all runtime domains.
- Data: [ownership](../../data/README.md).
- Tests: [domain test matrix](../../domains/platform/testing.md).
- Details: [domain README](../../domains/platform/README.md).
