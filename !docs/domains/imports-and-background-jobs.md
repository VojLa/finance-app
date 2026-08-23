# Imports and background jobs

## Scope and source of truth

Imports turn untrusted provider files into persisted batch/row/issue evidence
and then canonical transaction or investment writes. Jobs own durable execution,
lease/retry state, and publication coordination. Neither parser output nor job
progress is a financial read-model authority.

## Main flow

```text
Upload → batch registration → durable job → parse → normalize → deduplicate
  → classify → canonical posting → Holding rebuild → market/snapshot publication
```

Python entry points are `modules/imports/api.py`, `modules/jobs/api.py`,
`jobs/worker.py`, and `jobs/import_executor.py`. Browser routes live in
`src/app/api/import/`; the scoped client/job monitor lives in
`src/modules/imports/python/`.

## Ownership

- `imports/` owns upload limits, raw-file boundary, batch/row audit, parser
  selection, normalization, classification, and posting orchestration.
- Source parsers convert provider formats to internal forms and never directly
  access portfolio/snapshot persistence.
- `jobs/` owns durable status, leases, retries, worker lifecycle, publication
  targets, and completion transition.
- Investments/transactions own canonical writes; Holdings, market data, and
  snapshots own their respective derived stages.

## Invariants and verification

- Files, rows, and provider values are untrusted and bounded/validated.
- Raw payloads, tokens, checkpoints, leases, and backend diagnostics never
  cross public responses or logs.
- Repeated files/job retries cannot duplicate canonical finance.
- Multi-file import post-processes once per logical account/source batch.
- Unsupported data becomes parse-issue evidence, not accepted transaction data.
- Incomplete durable work remains behind the last complete published baseline.

Tests: `test_import_*`, `test_raiffeisenbank_*`, `test_trading212_*`,
`test_anycoin_*`, `test_background_job_*`, and import fixtures. Read
[import overview](../02-imports/01-overview.md),
[parser contract](../02-imports/02-parser-contract.md), and
[supported sources](../02-imports/03-supported-sources.md).
