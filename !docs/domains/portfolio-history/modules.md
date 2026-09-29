# Portfolio-history modules

Type: module
Status: current
Owns: snapshot-series reads, invalidation, scheduling and replay
Code: `portfolio_snapshot/history_reader.py`, `portfolio_history/`, `portfolio_history_rebuild/`
Update when: a snapshot-series layer, job, publication rule or dependency changes

| Area | Responsibility | Main entry points |
| --- | --- | --- |
| public read | authorize and read one exact published snapshot generation | `portfolio_snapshot/history_reader.py`, `portfolio_history/api.py` |
| invalidation | merge canonical, market and scope changes from the earliest affected time | `portfolio_history/invalidation/` |
| jobs/scheduler | durable rebuild/capture leases, retries and 30-minute capture cursor | `portfolio_history/jobs/`, `portfolio_history/scheduler/` |
| replay | deterministically reconstruct account state from canonical evidence | `portfolio_history_rebuild/`, `portfolio_history/builder/` |
| snapshot materialization | write and validate Account, InvestmentAccount, Portfolio and NetWorth snapshots | `snapshot_series/`, `snapshot_refresh/` |
| publication/retirement | atomically switch or retire the user pointer with a causal fence | snapshot-series executor and builder finalizer |

The `portfolio_history` package name remains for route compatibility and range
policy. It owns no `PortfolioHistory*` database persistence. Revisions
`3y0001snapshotjobs` and `3z0001historydrop` migrated the durable work and removed
the former generation, point, coverage, audit, compaction and cleanup layers.
