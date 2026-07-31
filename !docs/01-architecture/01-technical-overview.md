# Technical Overview

Finance App is a modular monolith with a Next.js web application, a Python
FastAPI service, PostgreSQL, and a small Rust workspace reserved for future
calculation engines.

```text
Browser -> Next.js UI and legacy route handlers
             \-> authenticated server adapter -> FastAPI /api/v1 -> PostgreSQL
                                                    |
                                              local raw-import storage
```

## Runtime responsibilities

- **Next.js / TypeScript** provides the current UI, NextAuth session, and legacy
  routes. It now also owns bodyless portfolio/dashboard snapshot workflow
  routes that bridge a verified session to FastAPI with a short-lived internal
  token. The pages have not yet migrated to those routes.
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

The target architecture is API-first, with Python owning financial workflows
and Next.js serving as UI and thin session/transport adapter. The 5M-B adapter
implements that transport boundary for coordinated refresh plus exact
portfolio/dashboard reads. FastAPI OpenAPI deterministically generates the
TypeScript transport types. The adapter performs no finance, account
discovery, or latest lookup; portfolio and dashboard page cutovers remain in
5M-C and 5M-D.
