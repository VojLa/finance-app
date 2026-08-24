# Imports and jobs

Type: domain
Status: current
Owns: file intake, batch/row evidence, parsers and durable job coordination
Code: `modules/imports/`, `modules/jobs/`, `src/modules/imports/python/`
Update when: parser, stage, job, retry or publication behavior changes

Untrusted files become persisted batch, row and issue evidence before canonical posting. Jobs own leases, retries, worker lifecycle and publication coordination. Retry and multi-file execution cannot duplicate canonical finance; incomplete work stays fenced at the last complete baseline.

Verification: [test matrix](testing.md). Recovery: [runbook](../../operations/import-and-job-recovery.md).

Details: [parser contract](parser-contract.md) and [supported sources](supported-sources.md).
