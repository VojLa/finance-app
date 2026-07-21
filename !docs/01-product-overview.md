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
- Import-batch registration, verified raw-file upload, CSV parsing, and generic
  row normalization.
- A basic portfolio read endpoint over accessible accounts, holdings, and the
  latest stored FX rates.
- PostgreSQL persistence through async SQLAlchemy and Alembic-owned migrations.

## Not yet delivered end to end

The target `import -> ledger -> holdings -> snapshots -> dashboard` workflow is
not complete. In particular, normalized import rows are not posted to
transactions or investment events, and there are no Python endpoints for
transactions, ledger replay, snapshot refresh, or dashboard reads. The current
Next.js UI still relies on legacy TypeScript API routes for its primary flows.

See [`!planning`](../!planning/README.md) for the intended product scope and
milestone acceptance criteria.
