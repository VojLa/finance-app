# Data Flow

## Implemented durable import flow

```text
browser upload -> Next.js allowlist -> register/upload ImportBatch -> enqueue one PostgreSQL job -> HTTP 202
                                                                        |
                                                                        v
worker claim -> parse -> normalize -> deduplicate -> classify -> canonical post
             -> Holdings rebuild -> reconcile member publication buckets
             -> direct market/FX evidence -> per-member atomic snapshots
             -> atomically publish targets + complete job -> portfolio/dashboard refresh
```

1. A writer submits one account, one supported source, and CSV files. Next.js
   verifies the session, validates an aggregate 64 MiB boundary, preserves exact
   bytes, and does no parsing or finance calculation.
2. Python registers each batch using source, immutable metadata, and SHA-256.
   An exact replay returns the same scoped batch; mismatched or foreign metadata
   fails closed. The raw body is verified and atomically published to local
   storage.
3. Next.js enqueues one durable job for all successfully uploaded batch IDs and
   returns HTTP 202. A partial safe file rejection does not orphan the other
   accepted batches.
4. The Python worker claims a fenced lease. Parsing runs off the API event loop
   and persists every physical row. Normalize, deduplicate, classify, and
   canonical posting advance durable checkpoints and reconcile exact replay.
5. Immediately before final snapshot acquisition, publication reconciles one
   durable minute `ImportJobPublicationTarget` for each current account member.
   A same-user bucket collision reserves the earliest free later minute and puts
   the job in `retry_wait` without consuming its attempt. A target without its
   own job-linked anchor may move forward on a later retry even if unrelated
   manual evidence occupies its old minute; that evidence is never deleted. An
   anchor remains immutable only while it proves the current canonical revision.
   A canonical change before atomic completion sends the job to `retry_wait`,
   retires only its unpublished stale anchor/target, and reacquires a fresh
   later bucket. Shared finalization derives
   affected finance from persisted canonical rows, rebuilds Holdings, obtains
   only required persisted direct provider evidence, and persists one exact
   minute `import_event` anchor per current member. For a viewer, this refresh
   is a narrow system-owned publication of the imported shared account only;
   unrelated viewer accounts remain reuse-only. The anchors reuse exact
   snapshot lineage and do not invent a historical daily market observation.
6. The browser polls a safe job DTO with bounded backoff. While an import is
   `queued`, `running`, `retry_wait`, or `failed`, current-value reads keep each
   affected account on its last published baseline so committed intermediate
   batches cannot leak into portfolio or dashboard. Only a validated
   `completed` result releases that publication fence and triggers a serialized
   portfolio/dashboard refresh. Under the same account membership lock, every
   current-member target receives `publishedAt` and the job becomes completed
   in one transaction. The same transaction locks and revalidates the account
   canonical revision represented by every anchor, serializing canonical posts
   with the completion boundary. A failed or incomplete job stays fenced. A failed
   refresh keeps the last ready snapshot visible and supports retry. After
   completion, the exact member anchor is the coherent starting point for
   current-value reads. Portfolio history applies the same publication fence:
   normal snapshots remain readable, but an `import_event` net-worth row is
   visible only through its exact baseline, published per-user target, and
   completed job. Orphaned, stale, running, and failed import rows are hidden.

Multi-currency buys keep listing-currency quote average separately from an
ordered settlement `costBasisByCurrency`. Snapshot projection converts every
component through its required direct pair; it never invents an inverse, pivot,
CNB, Yahoo, or synthetic fallback. Lease expiry, worker crash, duplicate enqueue,
and response loss converge on the same canonical job and finance identities.
