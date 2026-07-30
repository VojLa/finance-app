# 0004 Keep read models separate from financial history

## Status

Accepted; the basic legacy portfolio reader plus the 5L-A pure projection and
5L-B exact persisted AccountSnapshot reader are implemented.

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
  Step 5L-B adds the persisted exact read-only adapter: it selects no latest
  snapshot, reads no live Holding, PriceSnapshot, or ExchangeRate, and maps
  physical AccountSnapshot evidence into that pure contract without a write or
  lock.
- Step 5L-B deliberately adds no authorization boundary, public API, User or
  membership selection, multi-account aggregate, or dashboard projection.
  Those presentation boundaries remain staged from 5L-C onward.
- Rebuild, idempotency, correction, and concurrency rules must be specified and
  tested before the posting pipeline is introduced.
