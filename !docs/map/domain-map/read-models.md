# Portfolio and dashboard map

Type: domain-map
Status: current
Owns: L1 routing for portfolio and dashboard read models
Code: portfolio/snapshot/dashboard readers and browser presentation modules
Update when: read-model ownership, entry point or dependency changes

ID: `DOM-READ`
Purpose: authorized portfolio and financial-dashboard projections
Source of truth: selected snapshot and current-value evidence

- Entry points: portfolio snapshot, dashboard snapshot and same-origin adapters.
- Modules: `portfolio/`, `portfolio_snapshot/`, `dashboard_snapshot/`.
- Depends on: identity, accounts and valuation.
- Browser: `src/modules/portfolio/`, `src/modules/dashboard/`.
- Tests: [domain test matrix](../../domains/read-models/testing.md).
- Details: [domain README](../../domains/read-models/README.md) and [modules](../../domains/read-models/modules.md).
