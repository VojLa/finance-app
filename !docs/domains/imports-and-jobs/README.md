# Imports and jobs

Type: domain
Status: current
Owns: file intake, batch/row evidence, parsers and durable job coordination
Code: `modules/imports/`, `modules/jobs/`, `src/modules/imports/python/`
Update when: parser, stage, job, retry or publication behavior changes

Untrusted files become persisted batch, row and issue evidence before canonical posting. Jobs own leases, retries, worker lifecycle and publication coordination. Retry and multi-file execution cannot duplicate canonical finance; incomplete work stays fenced at the last complete baseline.

## Capabilities and boundaries

- register bounded uploads and preserve batch, row and issue evidence;
- parse, normalize, deduplicate, classify and post supported sources;
- reconcile source-specific evidence and build canonical posting plans;
- execute durable jobs with leases, retry and publication fencing;
- acquire and persist event-date Anycoin BTC transfer valuation evidence before
  Holding rebuild and snapshot publication;
- finalize multi-file work once per source/account batch.

Parsers never become finance authority, and incomplete work never replaces the last
published baseline.

## Navigation

- [Module and layer map](modules.md)
- [Parser contract](parser-contract.md) and [supported sources](supported-sources.md)
- [Import publication flow](../../architecture/flows/import-publication.md)
- [Canonical/publication invariants](../../architecture/invariants/canonical-and-publication.md)
- [Recovery runbook](../../operations/import-and-job-recovery.md)
- [Test matrix](testing.md)
