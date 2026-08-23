## Durable logical multi-file import

R12 separates request-lifetime upload from durable execution. The active browser
request accepts one account, one source, and one to ten files with a 64 MiB
aggregate bridge limit. Each accepted file retains its own `ImportBatch`; after
registration and byte-exact upload, Next.js enqueues exactly one account-scoped
`import_workflow` job containing the sorted batch IDs and returns HTTP 202.

PostgreSQL is the job lifecycle authority. An embedded Python worker claims jobs
with a fenced lease and advances parse, normalize, deduplicate, classify,
canonical-post, and shared finalization checkpoints. Checkpoint and business
writes are replayable after a crash. Automatic failures use bounded retry_wait;
an authorized manual retry resumes the same job identity. Concurrent enqueue,
claim, heartbeat, checkpoint, completion, and retry paths are serialized or
fenced so they cannot duplicate canonical finance.

The finalizer derives every financial selector from persisted evidence. After
the replayable batch stages and immediately before snapshot acquisition, it
reconciles one minute `ImportJobPublicationTarget` for each current account
member. Same-user bucket collisions reserve the earliest free later minute and
move the job to `retry_wait` without consuming an attempt. A target with no
job-linked anchor may move forward on retry even when unrelated manual snapshot
evidence occupies its former minute. An unpublished anchor stays fixed while its
canonical boundary is current; a later canonical write produces a safe retry,
retires only stale job-linked evidence, and requires a fresh target. Departed
members' unpublished targets and anchors are
retired under the account lock, while newly added members receive targets before
completion. It rebuilds Holdings once and
coordinates direct market/FX evidence plus per-member snapshot publication. A
job becomes `completed` only for `created`, `replayed`, or `not_required` after
an exact anchor exists for every current member. A duplicate-only replay still
runs this publication path instead of bypassing the anchor; unavailable evidence leaves the
prior complete manifest readable and the job retryable. The browser never
supplies Holding selectors, market plans, timestamps, calculation versions,
output currency, publication targets, or refresh overrides.

An import publication persists one narrow minute baseline anchor for every
current member from the same exact `import_event` snapshot graph. Ordinary
scheduled baselines remain day-granularity. The minute exception is restricted
to `import_event`, so current-value reads can start from the newly published
historical import without pretending that present-time provider evidence existed
at midnight. For a viewer, the worker may force-refresh only the imported shared
account under that target; unrelated viewer accounts remain reuse-only and no
HTTP privilege expands.

Current-value reads add an account-scoped publication fence around that durable
workflow. An accessible account with an import job in `queued`, `running`,
`retry_wait`, or `failed` is projected from its last published baseline;
post-baseline canonical changes for that account are withheld. The service
revalidates the same job set before planning and projection, and fails closed if
the lifecycle or member set changes concurrently. Under the account membership
lock, completion atomically sets every exact target `publishedAt` and the job
status. The same transaction locks `AccountCanonicalState` and requires every
member anchor to carry the current imported-account canonical revision. Only
that completed publication releases the fence. Portfolio and
dashboard share this service.

The snapshot-version module owns one narrow rollout exception for this fence.
An unfenced current read accepts only coordinated version 3. A read with at
least one actively fenced account accepts the explicit set `{2, 3}`, allowing a
coherent completed v2 publication to survive an incomplete v3 import. This is
not baseline fallback: version 1 and unlisted versions fail, and the selected
root must still pass the full account graph, NetWorth recomputation, manifest,
canonical lineage, active-membership, source-policy, and market-evidence checks.

Raw files remain local in R12. Therefore the embedded worker is a single-instance
deployment boundary unless every instance mounts the same import storage. The
PostgreSQL queue itself is safe for multiple claimers, but it does not make local
raw bytes portable.
