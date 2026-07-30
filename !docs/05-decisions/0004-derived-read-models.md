# 0004 Keep read models separate from financial history

## Status

Accepted; the basic legacy portfolio reader plus the 5L-A pure projection,
5L-B exact persisted AccountSnapshot reader, 5L-C authorized exact API, and
5L-D pure multi-account aggregation and 5L-E pure dashboard projection are
implemented, together with the 5L-F authorized public integration.

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
- Step 5L-C adds an account-specific authorized API over the unchanged 5L-B
  reader. Explicit owner/admin/editor/viewer access and the exact read share one
  fresh `REPEATABLE READ` transaction; foreign, missing, and archived accounts
  are not disclosed.
- The 5L-C response uses JSON strings for Decimal values and excludes internal
  lineage, membership/User data, and persisted audit JSON. It does not
  recalculate finance or select Holdings, prices, or FX.
- Step 5L-D aggregates only complete 5L-A views sharing exact snapshot
  metadata. It keeps positions account-scoped, canonically orders accounts,
  uses exact Decimal summary sums, and fails when MONEY range or aggregate
  formulas are not preserved.
- Step 5L-D has no database, authorization, reader, endpoint, price/FX
  selection, or Holding access.
- Step 5L-E projects exactly one complete 5L-D view into a summary, account
  cards, asset-type allocations, and a global account-scoped position ranking.
  Its allocations use aggregate investment value, never the account-local
  denominator. Liabilities remain summary-only and zero-investment results
  contain no investment breakdown.
- Step 5L-E performs no database read, authorization, snapshot selection,
  Holding, price or FX lookup, endpoint work, or historical comparison.
  Step 5L-F composes it without changing that pure boundary.
- Step 5L-F requires an explicit exact account selector set and performs no
  membership-based account discovery or latest/fallback selection. One
  `REPEATABLE READ` transaction contains every access check and exact 5L-B
  read, followed by one 5L-D aggregation call. The dashboard adapter calls
  5L-E exactly once and owns no database transaction.
- The public portfolio response preserves account-local allocation; the
  dashboard response exposes aggregate-denominator allocation. All financial
  Decimal values are JSON strings. Foreign, missing, and archived accounts are
  not distinguished, partial results do not exist, and the legacy and exact
  single-account endpoints remain unchanged.
- Rebuild, idempotency, correction, and concurrency rules must be specified and
  tested before the posting pipeline is introduced.
