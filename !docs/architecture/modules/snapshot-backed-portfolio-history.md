# Snapshot-backed portfolio history

Type: module
Status: current
Owns: published snapshot-series reads and their generation boundary
Code: snapshot readers, rebuild worker and same-origin portfolio adapters
Update when: snapshot projection, reader, worker or publication ownership changes

The portfolio graph is backed by one exact `UserReadModelPublication` generation.
The reader resolves that pointer and reads the matching
`PortfolioSnapshot`/`InvestmentAccountSnapshot`/`AccountSnapshot`/
`NetWorthSnapshot` graph. It never assembles a series from live Holdings,
current prices, current FX, or the private legacy history calculator.

Rebuilds are staged from canonical replay. The worker writes the complete target
manifest and all dependent snapshots before atomic pointer publication. Current
snapshot capture is independent from historical rebuilds, and provider I/O is
restricted to the builder/worker boundary.

Every snapshot output has an explicit output currency and retains native
currency evidence. A scalar is a derived user-output presentation value; it does
not erase the source-currency cash, investment, cost-basis or P/L breakdowns.

The legacy `PortfolioHistoryGeneration` tables and builder have been removed.
The retained `portfolio_history` package owns only API compatibility, range
policy and durable snapshot-series orchestration; it does not persist a second
financial history.

See [portfolio history publication](../flows/portfolio-history.md),
[money and currency invariants](../invariants/money-and-currency.md), and
[snapshot contracts](../../domains/evidence/snapshot-contracts.md).
