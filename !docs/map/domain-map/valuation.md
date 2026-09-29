# Valuation map

Type: domain-map
Status: current
Owns: L1 routing for snapshots, baselines, current value and net worth
Code: valuation and snapshot-refresh modules
Update when: valuation ownership, entry point or dependency changes

ID: `DOM-VALUE`
Purpose: immutable snapshots, baselines, current value and net worth
Source of truth: persisted snapshot evidence and validated baseline lineage

- Entry points: snapshot, current-value, net-worth and refresh APIs.
- Modules: `snapshots/`, `daily_baselines/`, `current_value/`, `net_worth/`, `snapshot_refresh/`.
- Depends on: canonical finance, liabilities and market evidence.
- Used by: portfolio and dashboard read models.
- Tests: [domain test matrix](../../domains/valuation/testing.md).
- Details: [domain README](../../domains/valuation/README.md) and [modules](../../domains/valuation/modules.md).
