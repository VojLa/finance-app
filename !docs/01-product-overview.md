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
and dashboard adapters call the strict current endpoints. Version 0.1 is not
yet complete, however: at the R10 final audit base, authenticated principal
resolution leaves the shared database session in a transaction before the D1
selector requires an idle session. Both current endpoints therefore fail
closed with `current_value_unavailable`. The D1/D2 engine itself succeeds when
invoked with a correctly composed idle session; R10-E1 must close the real HTTP
composition gap before the architecture milestone can pass.

See [`!planning`](../!planning/README.md) for the intended product scope and
milestone acceptance criteria.
