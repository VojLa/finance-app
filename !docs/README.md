# Finance App documentation

This directory describes the repository as implemented, not only its target
architecture. Product intent and the planned milestones remain in
[`!planning`](../!planning/README.md).

## Current implementation snapshot

The application is in the internal `0.1` architecture milestone. The Python
FastAPI service has working authentication, account, invitation, import-batch,
and portfolio read endpoints. PostgreSQL schema ownership has moved to
SQLAlchemy and Alembic. The Next.js application still calls its legacy
TypeScript route handlers for its main UI workflows, and the Python import
pipeline currently stops after duplicate detection; it does not yet post
transactions or investment events or rebuild holdings and snapshots.

## Reading guide

- [Product overview](01-product-overview.md), [domain model](02-domain-model.md), and
  [glossary](03-glossary.md) describe the business vocabulary and implementation status.
- [`01-architecture`](01-architecture/) describes runtime boundaries, modules, data flow,
  and security.
- [`02-imports`](02-imports/) documents the implemented import pipeline and its limits.
- [`03-api`](03-api/01-conventions.md) is the HTTP integration guide. The live OpenAPI
  schema is available from the Python service when documentation is enabled.
- [`04-development`](04-development/) contains local setup, checks, and coding rules.
- [`05-decisions`](05-decisions/) mirrors the short, implementation-facing architectural
  decisions. The full ADR record lives in [`!planning/decisions`](../!planning/decisions/).

When documentation conflicts with code, treat the code, its tests, and the live
OpenAPI document as the immediate runtime truth; update this directory in the
same change that resolves the discrepancy.
