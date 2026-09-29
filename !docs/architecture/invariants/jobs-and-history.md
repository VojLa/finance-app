# Jobs and portfolio-history invariants

Type: invariant
Status: current
Owns: `INV-JOB-*` and `INV-HISTORY-*`
Code: snapshot-series jobs, scheduler, rebuild and published snapshot readers
Update when: lease, retry, invalidation, publication or replay changes

| ID | Exact rule | Primary enforcement | Representative evidence |
| --- | --- | --- | --- |
| `INV-JOB-001` | Only the current lease owner and version may commit a durable job transition. | snapshot-series repository and worker | lifecycle, retry and schema tests |
| `INV-JOB-002` | Retry is bounded and resumes with the same persisted checkpoint and deterministic snapshot identity. Receipt-backed retry performs administrative finalization before replay or provider access; a scheduled capture gets at most one explicit transient-only 5-to-10 attempt recovery cycle. | job service, checkpoint and executor | executor, crash-after-switch and scheduler exhaustion tests |
| `INV-HISTORY-001` | Readers select one atomically published complete snapshot generation; empty scope retires it through the same causal fence. | snapshot publication and history reader | snapshot-series and API tests |
| `INV-HISTORY-002` | Canonical, market or scope changes persist an invalidation and rebuild from the earliest affected time. | invalidation service and scheduler | invalidation and late-import tests |
| `INV-HISTORY-003` | A rebuild writes staged snapshots and may resolve only the exact claimed dirty epoch after a lease-fenced publication. | snapshot executor and finalizer | publication, idempotency and failure tests |
| `INV-HISTORY-004` | A public range contains at most 480 ordered, timestamp-unique points from the exact publication and does no provider I/O or financial replay. | snapshot history reader and API adapter | reader, contract and performance tests |
| `INV-HISTORY-005` | Only accepted account memberships authorize account-filtered reads or satisfy a published portfolio scope; pending invitations have no read access. | snapshot history reader membership predicates | pending, revoked and accepted membership reader tests |
