# Technical Overview

Finance App is a modular monolith with a Next.js web application, a Python
FastAPI service, PostgreSQL, and a small Rust workspace reserved for future
calculation engines.

```text
Browser -> Next.js UI and legacy route handlers
             \-> planned authenticated adapter -> FastAPI /api/v1 -> PostgreSQL
                                                     |
                                               local raw-import storage
```

## Runtime responsibilities

- **Next.js / TypeScript** provides the current UI, NextAuth session, and legacy
  routes. The UI has not yet migrated its main workflows to FastAPI.
- **Python / FastAPI** owns the new HTTP transport, request infrastructure,
  account and invitation services, import-batch processing, and the temporary
  portfolio read endpoint.
- **PostgreSQL 16** is the central persistence store.
- **SQLAlchemy** provides the async runtime mappings for all application tables.
- **Alembic** is the sole owner of schema migrations. Prisma Client remains a
  Next.js compatibility layer; its migration history is frozen.
- **Rust** currently contains only a prototype calculation crate. It is not
  called by Python and must not be used as a source of financial truth yet.

The FastAPI service starts an async SQLAlchemy engine during its lifespan and
never applies migrations or DDL at application startup. The root endpoint lists
the available service endpoints; `/api/v1/health/live` and
`/api/v1/health/ready` are intended for orchestration.

The target architecture is API-first, with Python owning the business workflow
and Next.js serving as UI and thin session/transport adapter. That boundary is
documented in `!planning`; it is not fully realized in the current UI.
