# 0004 - Separate Read Models From Canonical History

## Decision

Portfolio, dashboard and reporting responses are read models built on top of canonical domain data.

## Why

- history and business truth must remain in ledger-like canonical structures
- UI needs optimized responses and cached historical views
- avoids mixing presentation with canonical storage

## Consequences

- read models are not source of truth
- snapshots and aggregates must be rebuildable
- portfolio and dashboard must share the same financial definitions
