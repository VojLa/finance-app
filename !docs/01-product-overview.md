# Product Overview

Finance App is a personal-finance and investment-tracking application. Its
long-term goal is one auditable view of accounts, cash, transactions,
investments, portfolio history, and net worth across banks, brokers, and
exchanges.

The core principle is that financial history belongs to the backend and that
derived views can be reproduced from canonical data. Every account has a main
currency; account-level values are expressed in that currency while native
currency breakdowns are retained.

## Current delivered backend scope

- Bearer-token authentication for the Python API through a trusted Next.js
  session bridge.
- Account creation, editing, archival, membership management, and invitations.
- Source-specific Raiffeisenbank, Trading212, and Anycoin import processing,
  canonical posting, canonical revision lineage, multi-file finalization, and
  Holdings rebuilding.
- Persisted market evidence, AccountSnapshot/NetWorthSnapshot graphs, exact
  daily-baseline lineage, and a strict baseline-plus-delta current-value engine.
- Exact portfolio, dashboard, and persisted NetWorth history projections with
  User.baseCurrency aggregates and Account.currency presentation values.
- PostgreSQL persistence through async SQLAlchemy and Alembic-owned migrations.

## Not yet delivered end to end

The production finance path is Python-owned and the active browser portfolio
and dashboard adapters call the strict current endpoints. R10-E1 makes the
persisted-principal lookup an explicit read phase that leaves the shared session
idle before D1/D2 begins; both real authenticated endpoints therefore reach the
current-value engine. Version 0.1 is not yet complete: mixed-currency composed
MONEY can retain more than the public contract's canonical six decimal places
during serialization, so the browser correctly rejects that otherwise exact
response. R10-E2 must close this response-contract gap.

See [`!planning`](../!planning/README.md) for the intended product scope and
milestone acceptance criteria.
