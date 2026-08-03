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
  token. The portfolio and dashboard pages consume their respective snapshot
  workflow routes for current financial views. The dashboard also temporarily
  reads operational widgets from its legacy route.
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
discovery, or latest lookup.

The 5M-C portfolio page cutover makes the snapshot workflow response the sole
authority for current portfolio cards and positions. The account selector is a
local projection over exact aggregate and account-scoped server views and
issues no request. Decimal strings remain unchanged; the page performs no
totals, P/L, return, allocation, FX, pricing, or fallback calculation. The
legacy history endpoint remains chart-only and cannot override current
snapshot values. The legacy current portfolio route remains registered but is
no longer called by the page.

The 5M-D dashboard cutover likewise makes the snapshot workflow the sole
authority for the financial summary, financial account cards, server-calculated
asset allocation, and server-ranked top positions. The page no longer consumes
legacy financial summary or balance fields. A separate temporary legacy request
is narrowed to operational current-month cash flow, budget, categories, trends,
and recent transactions; it cannot act as a financial fallback. Snapshot and
operational states and errors remain independent.

The 5M final audit closes the snapshot application cutover without production
changes. It proves the authenticated browser-to-Next-to-FastAPI path, exact
manifest transport, cross-runtime token compatibility, token-per-request
behavior, explicit empty handling, Decimal-string preservation, and the
absence of legacy financial fallback. Portfolio current finance and dashboard
finance are snapshot-backed. Portfolio history remains legacy chart-only;
dashboard operational widgets remain legacy and narrowly adapted. The legacy
current portfolio and dashboard routes remain compatibility surfaces.
Frontend-only GitHub Actions coverage remains a separate process risk. The
subsequent 0.1 final acceptance audit identified remaining release blockers and
left version 0.1 incomplete.

The 0.1-R1 remediation cuts the main account management page over to the
existing Python account API. The browser calls only same-origin Next.js account
routes; those routes verify NextAuth once and delegate through the shared
server-only authenticated transport. Python now owns list, create, update and
archive for the used account flow. The generated OpenAPI schemas remain the
TypeScript HTTP type source.

The bridge exact-allowlists caller JSON and reconstructs Python success
responses from the exact public account field set; unknown response fields,
enum values, currencies, and timestamps fail closed. All nine Python account
types are selectable. Account type is immutable after creation. Page controls
mirror Python membership roles: owner/admin may edit and archive, editor may
edit, and viewer is read-only; Python authorization remains final.

All account collection consumers use the typed browser client. Settings uses
Python `role` and `relation_type`; import, portfolio manual-add, and
transactions distinguish account-load errors from empty account sets. The main
account page replaces destructive delete with archive and no longer reads or
presents the legacy account-cash/FX model. Sharing write UX is outside R1. The
legacy cash and share route files remain registered compatibility surfaces but
are not called by the main account page.
The 0.1-R2 and R3 remediations establish source-specific Raiffeisenbank
processing and fixture-backed Trading212/Anycoin upload-to-read-model evidence.
R4 cuts the production import page over to those existing Python staged APIs.
The browser makes one same-origin request; Next.js verifies the session,
preserves exact file bytes, and orchestrates the eight public Python stages
with a fresh token per request. Python remains the only parser, normalizer,
deduplicator, classifier, canonical writer, holdings, and snapshot authority.
Legacy preview and provider-specific routes remain compatibility surfaces but
are not used by the page.

Version 0.1 remains incomplete; the next remediation is 0.1-R5, production
Python price and FX evidence ownership.
