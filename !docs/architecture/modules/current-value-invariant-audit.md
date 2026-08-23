## Current-value invariant audit

The active current portfolio and dashboard adapters call the coordinated
manual refresh before every exact read. Python owns a current clock, floors it
to `SnapshotGranularity.minute`, executes market evidence before snapshot
creation, persists the complete primary/companion AccountSnapshot set and one
NetWorthSnapshot, and returns the only manifest the subsequent read may use.
The reader has no latest, nearest, or daily-baseline selector.

This is a complete current-minute refresh contract, not an implementation of
the authoritative daily-baseline-plus-post-event-delta contract. Snapshot
evidence repositories load current Holdings and all eligible transactions,
events, and movements through the requested bucket. A current request succeeds
without a daily row and creates a new minute graph when a daily row exists.

R10-D found that a strict delta engine cannot be added safely without new
evidence contracts. Physical AccountSnapshot rows contain no canonical event
watermark/inclusion manifest, physical NetWorthSnapshot rows contain no
selected AccountSnapshot manifest, and LiabilityBalance is a dated state
observation rather than a delta chain. A post-baseline backfill can therefore
have a financial timestamp before the baseline while being absent from that
baseline; neither timestamp-only filtering nor current Holding can prove the
correct delta boundary.

Future R10-D1 must define a server-owned complete daily baseline manifest,
canonical inclusion watermark, account/configuration identity, and fail-closed
invalidation rules. Only then may R10-D2 define a current state projector,
current price/FX as-of policy, historical event-date FX delta, and atomic
primary/companion projection. Browser callers must never choose any baseline,
account set, version, currency, evidence IDs, or event range.
