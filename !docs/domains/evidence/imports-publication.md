## Durable Raiffeisenbank reconciliation and publication

Type: historical
Status: historical
Owns: milestone evidence for reconciliation and publication
Code: import reconciliation/job implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

Revision `3p0001rbfoundation` records immutable import-source occurrence
identity, one exact reporting-FX evidence row per canonical transaction, and
normalized durable-job membership. It also permits versioned reconciliation
evidence on `TransactionPair` without rewriting historical pairs. It is the
current Alembic head, following `3n0001emptyhold` and `3o0001unkbasis`.

The durable Raiffeisenbank worker runs its job-wide stages after canonical
posting in this order: deterministic reconciliation, direct historical
reporting-FX acquisition, explicit credit-card/loan/mortgage liability
readiness, and coordinated snapshot finalization/publication. Reconciliation
creates or exactly replays versioned internal-transfer, credit-card-payment,
and cash-exchange pairs. Reporting evidence is one direct, persisted FX lineage
per canonical foreign-currency transaction; no inverse, pivot, synthetic rate,
or unrelated job evidence can satisfy it. Liability accounts require an
explicit latest-as-of `LiabilityBalance` before publication.

Composite foreign keys prove the representative row belongs to the declared
account/source batch, an optional canonical transaction belongs to the same
account, reporting evidence uses the recorded FX direction, and job memberships
retain their initiating user/account ownership. Pair and reporting evidence are
created unpublished. The finalization transaction reconciles the job manifest,
refreshes every affected account, stamps the evidence and publication targets,
and completes the job atomically. A failed, pending, or partially completed job
therefore cannot leak an operational reclassification or partial snapshot.

Operational transaction readers use one fail-closed Python projection. A row
whose import batch has durable job membership remains hidden until every
membership job is completed; a foreign job-bound row additionally needs exact,
published direct reporting evidence whose job is completed. Batches without a
durable membership remain explicitly legacy-visible. A pair changes the
effective operational type only after both its own `publishedAt` and its job
completion are present. Published internal-transfer, credit-card-payment and
cash-exchange legs remain available as audit rows but do not contribute to
income, expenses, categories, or budgets. Snapshot and worker repositories
continue to read canonical evidence before this operational publication gate.
The reader also proves a pair job's affected-account membership and a reporting
job's exact batch/account membership. Any pair with `publishedAt` without that
completed proof, or two such pairs touching one transaction, hides the
transaction rather than selecting an order-dependent or stale income/expense
result.
| Snapshots | — | `AccountSnapshot`, `AccountSnapshotItem`, `NetWorthSnapshot` | 5I account persistence and 5J-A pure net-worth projection |
