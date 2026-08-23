# Snapshots, baselines, current value, and net worth

## Scope and source of truth

Snapshot records, canonical boundaries, daily baselines, current projections,
and net-worth aggregation provide exact valuation evidence. Canonical
transactions/events/liabilities remain the underlying business history;
snapshots are derived but immutable once written.

## Responsibilities

- Calculate and persist primary user-base-currency account/net-worth snapshots.
- Persist explicit account-currency companion snapshots when presentation
  differs from base currency.
- Select and validate daily baseline lineage.
- Project current value as a strict baseline plus eligible later canonical roots.
- Coordinate market-backed refresh while respecting import publication fences.

FastAPI entry points are `modules/snapshots/api.py`, `current_value/api.py`,
`net_worth/api.py`, and `snapshot_refresh/api.py`. Main layers include
`snapshots/{calculation,writer,writer_repository}.py`, `daily_baselines/`,
`current_value/{delta_projection,service,repository}.py`,
`net_worth/{projection,writer,repository}.py`, and `snapshot_refresh/`.

## Evidence model

Primary snapshot values use `User.baseCurrency`; account presentation uses
`Account.currency` evidence. Native currency breakdowns retain source evidence
but are not replacement scalar totals. Snapshot-time value uses direct market
evidence as of the snapshot/current view. Historical deposits, P/L, fees, and
tax use direct FX as of their financial event.

## Invariants

- No `float`, synthetic inverse, cross-rate, or read-time conversion.
- A companion snapshot is explicit persisted evidence, never a relabelled
  primary snapshot.
- Daily baselines name exact included canonical revisions and required Holding/
  liability lineage; backfill invalidates an affected baseline.
- Current value is ephemeral and must not manufacture a history point.
- Import jobs fence reads at last complete published evidence until atomic
  completion releases them.
- Public financial values follow exact fixed scales and fail closed if not
  representable.

## Verification and related material

Tests: `test_account_snapshot_*`, `test_snapshot_*`,
`test_daily_baseline_*`, `test_current_value_*`, `test_net_worth_*`,
`test_r10b*`, `test_r10d*`, and `test_snapshot_refresh_*`. Read
[data flow](../01-architecture/03-data-flow.md) and the snapshot/current-value
sections of [the consolidated domain model](../02-domain-model.md).
