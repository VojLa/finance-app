# Finance App documentation

This directory describes the repository as implemented, not only its target
architecture. Product intent and the planned milestones remain in
[`!planning`](../!planning/README.md).

## Current implementation snapshot

The application is in the internal `0.1` architecture milestone. Next.js owns
the UI, NextAuth session, and thin authenticated transport adapters. Python
owns the active account, import, canonical ledger, Holdings, market evidence,
snapshot, daily-baseline, current-value, portfolio, dashboard, and history
workflows. PostgreSQL is the finance persistence authority and Alembic owns its
schema migrations.

The strict current-value engine is implemented as a D1 daily baseline plus
forward canonical changes and current persisted market evidence. The R10 final
audit nevertheless keeps Version 0.1 incomplete: the real authenticated
portfolio and dashboard current endpoints currently return a safe unavailable
response because principal lookup and the D1 selector share an incompatible
SQLAlchemy session transaction boundary. R10-E1 owns that release blocker.

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
