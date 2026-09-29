# Snapshot contracts

Type: evidence
Status: current
Owns: persisted snapshot-generation contracts and currency lineage
Code: snapshot models, rebuild writer and authorized snapshot readers
Update when: snapshot schema, generation publication or currency semantics change

Canonical transactions and investment events remain the immutable financial
source of truth. Snapshots are rebuildable read evidence. A rebuild materializes
a complete generation containing `AccountSnapshot`,
`InvestmentAccountSnapshot`, `PortfolioSnapshot` and `NetWorthSnapshot` for each
affected user target. The publisher validates the complete manifest and switches
the `UserReadModelPublication` pointer atomically.

The public portfolio/history API reads only the exact currently published
generation. It does not select an approximate latest snapshot, combine
generations, call providers, or recalculate finance. Current snapshot capture is
a separate workflow from backdated import rebuilds.

Each snapshot has an explicit output currency. Account-level output uses the
account currency; user-level portfolio and net-worth output uses the user's base
currency. Native cash, investment, cost-basis, invested/deposited-flow and P/L
amounts remain preserved by currency, alongside the derived output-currency
scalar. No native currency may be silently converted away. Event-date FX for
cash-flow history is distinct from valuation-time price/FX evidence.

Provider I/O is permitted only in the rebuild builder/worker. Staging and
publication are idempotent and fail closed on missing, conflicting or incomplete
evidence; an unsuccessful rebuild leaves the prior complete publication intact.

The former `PortfolioHistoryGeneration` builder, points, coverage and publication
tables are removed. `SnapshotSeries*` stores only durable orchestration evidence;
all financial values served to the UI are read from the published snapshot graph.
