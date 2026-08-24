# Portfolio history

Type: domain
Status: current
Owns: historical generation, invalidation, jobs and atomic publication
Code: `portfolio_history/`, `portfolio_history_rebuild/`, history adapter
Update when: generation, invalidation, scheduler or publication changes

Portfolio history is an exact separate read projection. Immutable generations, coverage and publication evidence are owned by history modules. A history point cannot overwrite current portfolio cards or positions.

Verification: [test matrix](testing.md). Publication rules: [invariants](../../architecture/invariants/canonical-and-publication.md).
