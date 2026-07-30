# 0004 Keep read models separate from financial history

## Status

Accepted; the basic legacy portfolio reader and the pure 5L-A snapshot-backed
portfolio view contract are implemented.

## Decision

Transactions and investment events are canonical history. Holdings, account
snapshots, net-worth snapshots, portfolio views, and dashboards are derived
read models and must be rebuildable from canonical records and historical market
data.

## Consequences

- A presentation aggregate may not become the only record of a financial event.
- The same financial metric must have one definition across portfolio and
  dashboard surfaces.
- Snapshot values use one explicit output currency (the Account currency by
  default) and retain native-currency breakdowns. Event-date FX is required for
  cost and deposit metrics.
- New portfolio and dashboard views use immutable AccountSnapshot evidence as
  their financial authority. They do not use live Holding plus latest FX to
  redefine snapshot values.
- The current FastAPI portfolio endpoint remains a temporary basic legacy reader:
  it reads existing Holdings and latest stored FX. Step 5L-A neither replaces
  nor modifies that endpoint.
- Step 5L-A defines only a pure, immutable single-account portfolio projection.
  It adds no persisted AccountSnapshot reader, repository, authorization
  boundary, public API, or dashboard projection.
- Rebuild, idempotency, correction, and concurrency rules must be specified and
  tested before the posting pipeline is introduced.
