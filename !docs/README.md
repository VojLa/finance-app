# Finance App documentation

This directory describes the repository as implemented, not only its target
architecture. Product intent and the planned milestones remain in
[`!planning`](../!planning/README.md).

## Current implementation snapshot

The application is in the internal `0.1` architecture milestone. Python owns
the identity, account, transaction, category, import, canonical ledger, Holdings,
market evidence, snapshot, daily-baseline, current-value, portfolio,
dashboard-snapshot, and history workflows. However, active Next.js/TypeScript
business paths still exist for operational dashboard data, budgets, and manual
investment operations. Some legacy compatibility paths still access PostgreSQL
through Prisma. PostgreSQL is the
finance persistence authority and Alembic owns its schema migrations.

The strict current-value engine is implemented as a D1 daily baseline plus
forward canonical changes and current persisted market evidence. R10-E1 closes
the authentication lookup transaction before D1/D2 takes ownership. R10-E2
canonicalizes every public MONEY value to the exact six-decimal wire contract
without changing financial arithmetic. Real authenticated mixed-currency
portfolio and dashboard responses now pass the strict browser validator.

The Python core of version 0.1 is implemented, but the strict Architecture
Locked boundary is under remediation until the remaining TypeScript/Prisma
business runtime is cut over and removed. This status is not a declaration of
public-production readiness.

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
