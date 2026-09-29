# Portfolio-history testing

Type: testing
Status: current
Owns: representative snapshot-series publication and read verification
Code: snapshot-series, snapshot history and historical market-data tests
Update when: history risks or representative suites change

| Risk | Invariant | Evidence |
| --- | --- | --- |
| Partial or foreign generation becomes visible | `INV-HISTORY-001` | snapshot publication, user isolation and API tests |
| Late import leaves old graph values | `INV-HISTORY-002` | invalidation, replay and late-import rebuild tests |
| Retry publishes a different or duplicate generation | `INV-JOB-002`, `INV-HISTORY-003` | checkpoint, idempotency and executor tests |
| Crash after pointer switch requires providers again | `INV-JOB-002` | receipt-first administrative-finalization test with forced provider failure |
| Unchanged prefix is replayed or copied | `INV-PUBLISH-004` | suffix replay-spy and exact prefix snapshot-ID integration tests |
| Permanent capture failure loops forever | `INV-JOB-002` | repeated scheduler-tick and attempt-ceiling tests |
| A stale worker clears newer invalidation | `INV-JOB-001`, `INV-HISTORY-003` | lease-version and exact dirty-epoch tests |
| Reader performs replay/provider I/O or mixes generations | `INV-HISTORY-004` | snapshot history reader, adapter and benchmark tests |
| Pending invitation reads published history | `INV-HISTORY-005` | account and portfolio pending-membership tests |
| Native currencies are lost | money/currency invariants | multi-currency snapshot and API tests |
| Legacy storage survives cutover | `INV-HISTORY-001` | `test_snapshot_series_schema_cutover.py`, migration policy and live schema parity |

The published-read benchmark covers 1, 5 and 20 accounts. The latest measured
p95 was 20.25/28.02/41.38 ms cold and 8.94/9.88/11.28 ms warm, with 11 cold and
5 warm SQL statements independent of account count. Operational-dashboard p95
was 9.24/15.01/19.07 ms with JIT enabled. Both remain below the 100 ms target on
the disposable local PostgreSQL benchmark environment.
