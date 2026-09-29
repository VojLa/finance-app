# Imports and jobs map

Type: domain-map
Status: current
Owns: L1 routing for imports and durable jobs
Code: import pipeline, source adapters, jobs and browser monitor
Update when: import/job ownership, entry point or dependency changes

ID: `DOM-IMPORTS`
Purpose: untrusted file intake, durable execution and guarded publication
Source of truth: persisted import batches, rows, issues and background jobs

- Entry points: import/job APIs, worker and import executor.
- Modules: `imports/`, `jobs/`, `src/modules/imports/python/`.
- Depends on: accounts, canonical writers, holdings, market evidence and valuation.
- Rules: [publication invariants](../../architecture/invariants/canonical-and-publication.md).
- Tests: [domain test matrix](../../domains/imports-and-jobs/testing.md).
- Details: [domain README](../../domains/imports-and-jobs/README.md) and [modules](../../domains/imports-and-jobs/modules.md).
