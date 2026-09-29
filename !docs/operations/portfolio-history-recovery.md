# Snapshot-series recovery

Type: runbook
Status: current
Owns: safe diagnosis and recovery of stalled snapshot rebuilds or captures
Code: snapshot-series invalidation, jobs, scheduler, replay and publication
Update when: job, checkpoint, retry or publication behavior changes

## Recovery sequence

1. Confirm the current published snapshot remains readable; recovery must not
   edit it in place.
2. Inspect `SnapshotSeriesDirtyState`, unresolved invalidations and the matching
   `SnapshotSeriesRebuildJob` lease, attempt count and checkpoint.
3. Retry through the job service. Never edit snapshot rows, publication pointers,
   dirty epochs or leases manually. A receipt-backed crash-after-switch retry
   must finalize without replay or provider access.
4. Let the worker replay canonical evidence, stage a complete deterministic
   generation and publish it atomically.
5. Verify the job result generation equals `UserReadModelPublication.generationId`
   and that only the claimed dirty epoch was cleared.

On a transient provider failure, retain the prior publication and retry according
to the bounded job policy. Scheduled capture has five initial attempts and at
most one transient-only recovery cycle up to ten cumulative attempts. Permanent
lookback unavailability is an operator-visible terminal state and is not
automatically requeued. Stop on an active foreign lease, ambiguous ownership,
missing canonical/market evidence, a changed dirty epoch or a publication identity
mismatch. Empty active scope is resolved by a causally newer retirement watermark,
not a synthetic financial snapshot.

For CoinGecko long-range coverage configure exactly one server-side credential:
`COINGECKO_PRO_API_KEY` or `COINGECKO_DEMO_API_KEY`. Do not fall back between
provider identities after an entitlement, quota or coverage failure.
