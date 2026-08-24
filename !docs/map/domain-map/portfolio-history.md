# Portfolio-history map

ID: `DOM-HISTORY`
Purpose: immutable historical generations and atomic publication
Source of truth: selected complete portfolio-history generation

- Entry points: history API, scheduler and durable history jobs.
- Modules: `portfolio_history/`, `portfolio_history_rebuild/`.
- Depends on: canonical finance and historical market evidence.
- Used by: portfolio chart reads only.
- Tests: [domain test matrix](../../domains/portfolio-history/testing.md).
- Details: [domain README](../../domains/portfolio-history/README.md).
