## Multi-file logical import execution

Type: historical
Status: historical
Owns: milestone evidence for multi-file import execution
Code: import and job implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R10-A introduces an application-level logical execution without introducing a
new physical entity. The persisted model remains:

- one `ImportBatch` per submitted file;
- canonical Transaction or InvestmentEvent lineage owned by that batch;
- one transient finalization command containing the canonical sorted set of
  successfully posted batch IDs.

The finalization identity is constrained by one authenticated principal, one
account, and one persisted `ImportSource`. Batch IDs are nonblank, unique, and
server-canonicalized before the immutable command is constructed. Every batch
must be terminal, owned by that principal, and belong to the requested
account. No financial plan or snapshot selector is part of the command.

The logical final timestamp is
`max(persisted ImportBatch.completedAt)`. Its snapshot identity uses the
canonical minute floor. This makes the result independent of multipart file
order and avoids a new clock. The aggregate imported-target counts decide
whether work is required; a zero total produces `not_required`.

If any batch contains imported investment events, the account Holding
projection is rebuilt once after all canonical batches commit. One
market-backed refresh then creates or replays the whole-user snapshot graph.
Per-file batch statuses remain unchanged, and there is no persisted fake group
status. The browser response adds only a request-level
`snapshotRefreshStatus`; internal market, snapshot, account-selection, and
provider identities remain private.

The logical execution is deliberately multi-phase rather than atomic.
Canonical batches already committed before a later file failure remain
truthful persisted partial state, while request-level finalization is not run.
Finalization failure preserves canonical finance and any valid phase already
committed. Completed/partially-completed file results and failed results whose
last successful stage is canonical `posted` retain their persisted batch IDs.
The browser can submit that exact set through the authenticated same-origin
finalization-retry adapter without uploading files again. The adapter adds no
financial fields; Python revalidates the complete persisted batch set before
replaying canonical state and converging through the existing immutable
Holding, market, AccountSnapshot, and NetWorthSnapshot contracts. Files that
failed before canonical posting and ordinary historical duplicates do not
produce a recovery identity.
