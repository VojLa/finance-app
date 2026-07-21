# 0004 Keep read models separate from financial history

## Status

Accepted; only the basic portfolio reader is implemented.

## Decision

Transactions and investment events are canonical history. Holdings, account
snapshots, net-worth snapshots, portfolio views, and dashboards are derived
read models and must be rebuildable from canonical records and historical market
data.

## Consequences

- A presentation aggregate may not become the only record of a financial event.
- The same financial metric must have one definition across portfolio and
  dashboard surfaces.
- Snapshot values use the account's main currency and retain native-currency
  breakdowns. Event-date FX is required for cost and deposit metrics.
- Current `Holding` and snapshot tables are schema support for this design, not
  proof of a working rebuild pipeline. The FastAPI portfolio endpoint only reads
  existing holdings and current stored FX.
- Rebuild, idempotency, correction, and concurrency rules must be specified and
  tested before the posting pipeline is introduced.
