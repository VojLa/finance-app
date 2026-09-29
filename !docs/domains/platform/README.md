# Persistence and frontend platform

Type: domain
Status: current
Owns: shared runtime, migrations, adapters and experimental-engine boundary
Code: `app/db/`, `app/shared/`, `app/config/`, `src/app/`, `src/modules/`, Rust
Update when: platform authority, generated contract or runtime integration changes

PostgreSQL, SQLAlchemy and Alembic form the persistence platform. Next.js provides presentation and same-origin adapters; generated API types are transport-only. `backend/rust/finance_engine` is experimental and not financial truth.

## Capabilities and boundaries

- create and configure the FastAPI application, lifespan and shared infrastructure;
- map all runtime PostgreSQL data through SQLAlchemy and migrate through Alembic;
- provide safe logging, request context, errors and decimal serialization;
- serve Next.js pages and same-origin transport adapters;
- generate OpenAPI-derived TypeScript types and enforce runtime boundaries.

The Rust engine and empty frontend namespaces have no production finance authority.

## Navigation

- [Module and runtime map](modules.md)
- [Frontend surfaces](frontend-surfaces.md)
- [Runtime boundaries](../../architecture/boundaries.md)
- [Data ownership](../../data/README.md)
- [Tooling](../../development/tooling.md) and [CI matrix](../../testing/ci-matrix.md)
- [Test matrix](testing.md)
