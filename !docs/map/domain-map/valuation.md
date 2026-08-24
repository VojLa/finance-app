# Valuation map

ID: `DOM-VALUE`
Purpose: immutable snapshots, baselines, current value and net worth
Source of truth: persisted snapshot evidence and validated baseline lineage

- Entry points: snapshot, current-value, net-worth and refresh APIs.
- Modules: `snapshots/`, `daily_baselines/`, `current_value/`, `net_worth/`, `snapshot_refresh/`.
- Depends on: canonical finance, liabilities and market evidence.
- Used by: portfolio and dashboard read models.
- Tests: [domain test matrix](../../domains/valuation/testing.md).
- Details: [domain README](../../domains/valuation/README.md).
