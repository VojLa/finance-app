## Daily baseline lineage foundation

Type: historical
Status: historical
Owns: milestone evidence for daily-baseline lineage
Code: baseline and canonical-lineage implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

R10-D1 adds two internal modules without changing the active browser flow.
`canonical_state` owns commit-ordered per-account revision allocation and its
append-only root journal. Transaction and LiabilityBalance each consume one
revision; one InvestmentEvent plus its atomic movement set consumes one
investment revision. The canonical writer, journal insert, and state update
share one transaction and one locked account-state row. Replay validates the
existing journal and consumes no revision.

The Holding rebuild locks the same state, rebuilds the complete investment
history, and atomically stamps `holdingRevision = lastInvestmentRevision`.
Non-investment revisions do not stale Holdings. A later investment event
advances only the investment watermark, so a day snapshot fails until rebuild
proves the new history.

For day granularity only, the AccountSnapshot writer captures one stable
canonical boundary for primary and account-currency companion projections.
Investment boundaries require a fresh Holding watermark; liability boundaries
retain and validate the exact selected LiabilityBalance journal identity.
Snapshots, items, companions, and boundaries remain one atomic writer
transaction.

`daily_baselines` persists a normalized manifest after the exact day
NetWorthSnapshot. The manifest retains the current active account set, exact
primary and presentation IDs, configuration, revision cutoffs, Holding
watermarks, and liability lineage. Its internal `REPEATABLE READ, READ ONLY`
selector chooses the newest candidate through an internal time bound and
validates it completely. A corrupt, configuration-stale, incomplete, or
backfilled newest baseline fails; there is no older/nearest fallback.

Canonical revision is inclusion order, not financial time. A journal root
committed after the cutoff with `financialTimestamp <= baseline.timestamp`
invalidates the baseline. A higher revision with a strictly later financial
timestamp is returned only as lineage for R10-D2; D1 performs no arithmetic,
price/FX selection, or current state projection. Portfolio and dashboard still
use the existing current-clock minute refresh until R10-D2.
