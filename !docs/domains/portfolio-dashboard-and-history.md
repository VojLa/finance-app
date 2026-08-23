# Portfolio, dashboard, and history

## Scope and source of truth

Portfolio, financial dashboard, and history are authorized read projections over
snapshot/current-value/net-worth evidence. They own no alternative financial
calculation or persistence truth. The operational dashboard is a separate
transaction/budget projection documented elsewhere.

## Main responsibilities

- Serve exact portfolio aggregate/account summaries, positions, and currency
  breakdowns.
- Serve snapshot-backed financial dashboard summary, account cards, allocation,
  and top positions.
- Serve selected immutable portfolio history/generation output for charts.
- Keep browser refresh/state behavior safe when publication or network failures
  occur.

Backend modules are `portfolio/`, `portfolio_snapshot/`,
`dashboard_snapshot/`, and `portfolio_history/`. Their main readers/projections
are `portfolio_snapshot/{authorized_reader,reader,aggregation}.py` and
`dashboard_snapshot/{authorized_service,projection}.py`. History additionally
owns builder, generation, invalidation, job, and scheduler submodules.

Browser entry points are the bodyless `/api/snapshot-workflow/portfolio` and
`/api/snapshot-workflow/dashboard` adapters, `/api/portfolio/history`, and
`src/modules/{portfolio,dashboard}/`.

## Invariants

- Browser state preserves decimal strings and does not sum, price, FX-convert,
  rank, or recover finance from a legacy response.
- Account presentation snapshot identity and aggregate primary snapshot identity
  remain explicit and are never mixed.
- Portfolio history is a separate exact read; a history point cannot overwrite
  current cards or positions.
- Snapshot and operational sections have independent state/error boundaries.
- Missing required companion/current evidence is unavailable, not reconstructed.

## Verification and related material

Tests include `test_portfolio_*`,
`test_authorized_portfolio_snapshot_reader.py`,
`test_dashboard_snapshot_projection.py`, `test_portfolio_history_*`, and
frontend portfolio/dashboard tests. Read
[portfolio history architecture evidence](../architecture/modules/snapshot-backed-portfolio-history.md)
and
[technical overview](../01-architecture/01-technical-overview.md).
