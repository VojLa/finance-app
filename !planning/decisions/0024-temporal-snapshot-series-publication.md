# ADR 0024 - Temporal links for complete snapshot-series publication

Status: Accepted
Date: 2026-09-28
Decision owners: finance-app owner
Extends: ADR 0022 - Unified renewable snapshot projections

## Context

The four immutable snapshot projections remain the only financial read models,
but a scheduled refresh currently stages one physical generation containing one
new point and moves `UserReadModelPublication` to it. History readers filter by
that generation, so the newly published current point hides the older complete
series. Copying all financial snapshot rows into a new generation every five
minutes would retain history but would create unbounded write amplification and
would duplicate unchanged financial evidence.

A backdated rebuild has a different shape: it must preserve the unaffected
prefix and replace every coordinate in the affected suffix, including points
that disappear. Publication must remain atomic, a failed build must leave the
last complete series visible, and retries and concurrent workers must not revive
an older state.

## Decision

### Immutable financial rows, versioned temporal links

Financial snapshot payloads stay immutable in `AccountSnapshot`,
`InvestmentAccountSnapshot`, `PortfolioSnapshot` and `NetWorthSnapshot`. A new
per-user snapshot-series head supplies a monotonically increasing version, and
temporal point-link rows associate a logical published coordinate with the exact
`DailySnapshotBaseline`, `PortfolioSnapshot` and `NetWorthSnapshot` identities.
The baseline continues to own the exact account and investment-snapshot links.

Each link has `validFromVersion` and an optional exclusive `validToVersion`.
For a head version `v`, a point is visible exactly when
`validFromVersion <= v < validToVersion`, with a missing upper bound treated as
infinity. PostgreSQL constraints prohibit overlapping version ranges for the
same user, timestamp and granularity, and permit at most one open range for that
coordinate.

An ordinary current refresh closes or adds only its affected coordinate and
therefore writes O(1) link metadata. A backdated rebuild closes every current
link at or after `dirtyFrom` and inserts the recomputed suffix; the unchanged
prefix is inherited through its still-open temporal intervals. Neither path
copies unchanged financial rows. Work is proportional to the changed suffix,
not the complete history.

### Atomic publication and read consistency

Publication runs in one `SERIALIZABLE` transaction. It locks the durable user
series version state and the current publication, verifies the captured parent
head, live account boundaries, causal watermark, staged manifest and exact
claimed dirty epoch, allocates the next never-reused version, applies all link
interval changes, creates the immutable head and publication receipt, and moves
`UserReadModelPublication` to that head. A refresh is rejected while a dirty
range exists. Competing publishers from the same parent cannot both commit.

The durable per-user version counter survives empty-scope retirement and starts
advancing again from its previous value when the user later republishes. Empty
scope uses the same causal watermark and creates no reusable version.

History reads obtain the publication head and all visible links in one SQL
statement, then join the exact linked snapshot identities. This prevents a
pointer/link race under the default `READ COMMITTED` isolation level. Link and
head garbage collection is deliberately out of scope for this stabilization:
all historical link versions are retained, so an in-flight old-head read cannot
lose its series. A future cleanup design must define a safe reader horizon before
deleting any versioned metadata.

### Retry, ownership and recovery

The publisher writes a durable receipt in the same transaction as the pointer
switch. A retry that finds its receipt performs only idempotent administrative
finalization before loading replay scope or calling a provider, even when a
newer publication is already current; it never writes financial snapshots a
second time and never moves the pointer backwards.

Staged generations carry their durable job and lease provenance. Scheduler
deferral requires a live running job with a matching, unexpired lease; a staged
generation without such ownership is abandoned evidence, not active work. A
stale job is terminally classified and a new job with a new causal timestamp is
scheduled when current state still requires work. Exact dirty-epoch equality is
required before clearing invalidation state, so an older completion cannot erase
a newer request.

For worker-owned publication, the `SERIALIZABLE` transaction first locks all
affected users in stable order and then the durable job lease row, before any
manifest or receipt read. This matches the scheduler's `User -> Job` order and
prevents a scheduler/publication lock cycle. Heartbeat renewal may then wait for
the short atomic switch, but cannot advance the lease row after the transaction
snapshot was established and cause a late conflict. Receipt-based replay remains
idempotent while holding the same fences. PostgreSQL serialization and deadlock
aborts retry the complete publication transaction at most three times from the
already frozen manifest; they never repeat market-data acquisition or financial
calculation.

A scheduled capture that exhausts its initial five worker attempts may receive
one automatic recovery cycle only for an explicitly classified transient error.
The cumulative attempt count is preserved and the ceiling becomes ten. Permanent
or actionable errors, including unavailable provider lookback, are terminal for
automatic scheduling; manual retry remains a separate bounded operator action.

Successful rebuild finalization also advances a stale scheduler cursor to the
first 30-minute boundary after the rebuild's `coveredThrough` value, without ever
moving a newer cursor backwards. This prevents a restored installation from
publishing every already rebuilt historical half-hour one job at a time; only
boundaries after the frozen rebuild horizon remain scheduler work.

## Required constraints

- one unique `(userId, version)` series head and one immutable head identity;
- a durable per-user `lastVersion >= 0` counter retained across retirement;
- `validFromVersion >= 1` and `validToVersion > validFromVersion` when present;
- unique `(userId, timestamp, granularity, validFromVersion)` point identity;
- no overlapping integer version ranges for one user/timestamp/granularity;
- at most one open interval for one user/timestamp/granularity;
- foreign keys from each point link to the exact user/generation snapshot
  identities and publisher validation of the baseline's account/investment links;
- one publication receipt per user/job/generation/head result.

## Consequences

- Scheduled refresh preserves the complete published series without recalculating
  or copying unchanged history.
- A backdated import replaces only the affected suffix while the previous
  complete publication remains readable until the atomic switch.
- One logical publication may intentionally reference immutable financial points
  created by several physical generations; the series head, not physical row
  co-location, is the atomic public-history boundary.
- Metadata grows with changed coordinates. Cleanup is postponed until a safe
  horizon protocol is accepted and tested.
- Publication, retry and scheduler tests must cover concurrent publishers,
  crash-after-switch retry, orphan staging, retirement/republication, suffix
  removal, newer dirty epochs and one-statement old-head reads.
