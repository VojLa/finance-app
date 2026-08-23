# Domain documentation

These documents are the primary L1 technical documentation for implemented
domains. Start with the [Domain Map](../map/DOMAIN-MAP.md), then read only the
module document that matches the change.

| Domain | Document |
| --- | --- |
| Identity, authentication, API bridge | [Identity and API boundary](identity-and-api.md) |
| Accounts, memberships, liabilities | [Accounts and liabilities](accounts-and-liabilities.md) |
| Cash ledger and categories | [Transactions and categories](transactions-and-categories.md) |
| Budgets and operational reporting | [Budgets and operational dashboard](budgets-and-operational-dashboard.md) |
| File ingestion and durable work | [Imports and background jobs](imports-and-background-jobs.md) |
| Investment ledger and derived positions | [Investments, canonical state, and holdings](investments-canonical-state-and-holdings.md) |
| Asset identity and valuation inputs | [Market data, prices, and FX](market-data-prices-and-fx.md) |
| Snapshot and live valuation | [Snapshots, baselines, current value, and net worth](snapshots-baselines-current-value-and-net-worth.md) |
| Financial read models and history | [Portfolio, dashboard, and history](portfolio-dashboard-and-history.md) |
| Database and process infrastructure | [Persistence, migrations, and runtime](persistence-migrations-and-runtime.md) |
| Browser presentation and Rust prototype | [Frontend and experimental Rust](frontend-and-experimental-rust.md) |

Detailed historical/cross-domain evidence is split into the
[domain evidence index](evidence/README.md) and
[architecture module evidence](../architecture/modules/README.md). The former
consolidated files are now short redirect indexes. Add current rules only to the
matching module document.
