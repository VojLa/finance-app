# Portfolio-history map

Type: domain-map
Status: current
Owns: L1 routing for snapshot-series rebuilds and historical reads
Code: snapshot history reader, rebuild, scheduler, jobs and server adapter
Update when: history ownership, entry point or dependency changes

ID: `DOM-HISTORY`
Purpose: renewable snapshot series, atomic publication and fail-closed reads
Source of truth: exact `UserReadModelPublication` snapshot generation

- Entry points: `GET /api/v1/portfolio/history`, scheduler and durable snapshot-series jobs.
- Modules: `portfolio_snapshot/history_reader.py`, `portfolio_history/`, `portfolio_history_rebuild/`.
- Depends on: canonical finance and historical market evidence.
- Used by: the same-origin `/api/portfolio/history` adapter and portfolio chart only.
- Tests: [domain test matrix](../../domains/portfolio-history/testing.md).
- Details: [domain README](../../domains/portfolio-history/README.md) and [modules](../../domains/portfolio-history/modules.md).
