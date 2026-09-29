## Current value versus daily-baseline delta

Type: historical
Status: historical
Owns: milestone evidence for current value and baselines
Code: current-value and baseline implementation at the recorded milestone
Update when: evidence is archived or replaced by a newer record

The authoritative Version 0.1 invariant defines current/live value as the
latest exact daily snapshot advanced by canonical events after that snapshot.
The observed production model currently implements a different persisted
identity: a current-clock, minute-aligned complete AccountSnapshot and
NetWorthSnapshot graph. Portfolio and dashboard read that exact graph; they do
not advance an older daily state.

A daily AccountSnapshot contains aggregate cash, investment, liability,
historical metrics, exact items, native breakdowns, and selected market audit,
but it does not contain the canonical event set or watermark included in those
aggregates. AccountSnapshotItem contains quantity and aggregate cost evidence,
not a canonical movement cursor. NetWorthSnapshot contains totals but does not
physically retain its selected primary AccountSnapshot manifest. Consequently,
a later-ingested backdated transaction or movement cannot be classified as
already in the baseline or part of the delta from persisted snapshot evidence
alone.

LiabilityBalance is an immutable effective-at state observation. Snapshot
calculation selects the unique latest eligible balance, but AccountSnapshot
does not persist a liability delta chain. Exact liability advancement from a
daily value is therefore unavailable. Current Holdings are rebuilt from full
movement history and cannot substitute for post-baseline event lineage.

Current valuation also needs a separately specified price and FX as-of
contract. Existing provider evidence is safely acquired and persisted by the
coordinated complete refresh. Historical net deposits, realized P/L, fees, and
taxes use event-date FX, while current cash, positions, and liabilities use
snapshot-time evidence. No independent daily-plus-delta market projection
currently owns both primary `User.baseCurrency` and companion
`Account.currency` outputs.

R10-D therefore leaves current production unchanged and records a NOT READY
representability verdict. A strict implementation first requires persisted
baseline membership and canonical cutoff evidence, then one server-side delta
projector that produces both currency authorities without read-time FX or
browser-selected lineage. History remains a separate persisted
NetWorthSnapshot series and receives no synthetic current point.

## Canonical revisions and eligible daily baselines

R10-D1 persists canonical inclusion independently of economic time. Every
Account has one `AccountCanonicalState`. `lastRevision` advances by exactly one
for each newly committed Transaction, InvestmentEvent root, or
LiabilityBalance. `lastInvestmentRevision` advances only for an InvestmentEvent
and `holdingRevision` identifies the exact investment revision represented by
the current Holding set. The append-only `AccountCanonicalChange` stores only
root identity, kind, financial timestamp, and commit-ordered revision; amounts,
currencies, quantities, and movements remain in their authoritative tables.

A newly created investment account has an exact empty Holding set, so its
canonical state starts with `lastInvestmentRevision = holdingRevision = 0`.
Non-investment accounts keep `holdingRevision = NULL`. The `3n0001emptyhold`
migration applies the same state to existing investment accounts only when
revision zero, no Holding rows, and no investment-event canonical roots prove
that the account is empty; ambiguous or stale states remain unchanged and fail
closed at the snapshot writer.

One InvestmentEvent and its atomic InvestmentMovement set are one revision.
LiabilityBalance remains a replacement observation rather than an additive
delta. Exact replay validates the journal without advancing state. The account
state row lock makes visible revision order equivalent to committed canonical
state order and prevents sequence gaps caused by independently allocated
numbers.

Every newly created day AccountSnapshot and every publishable minute snapshot
(`import_event`, `manual_recalculation`, `price_refresh`, or `scheduled`) carries
one immutable `AccountSnapshotCanonicalBoundary`. Cash accounts retain the canonical cutoff.
Investment accounts also require equal investment and Holding watermarks.
Liability accounts retain the exact selected LiabilityBalance ID and validate
that its journal revision was included. A mixed-currency primary and companion
pair shares identical canonical, Holding, and liability lineage.

`DailySnapshotBaseline` names one exact day NetWorthSnapshot. Its normalized
account rows record every active supported account exactly once, with account
type/currency, exact primary and presentation snapshot IDs, revisions, Holding
watermark, and selected liability. NetWorth continues to contain primaries
only. Same-currency presentation may reuse the primary identity; a
mixed-currency presentation must name its companion.

The internal newest-baseline selector validates user base currency, current
active account set, account type/currency/archive state, calculation version,
all snapshot and boundary identities, contiguous physical journal roots,
fresh Holdings, and liability lineage. If the newest candidate is invalid it
fails closed and never selects an older baseline.

Changing `User.baseCurrency` therefore makes every baseline in the prior currency
unavailable immediately. Current-value repeats this exact-baseline validation in
its read-only planning and projection transactions, so it cannot relabel the old
aggregate while the next correctly denominated baseline is being produced.

A later revision with `financialTimestamp <= baseline.timestamp` proves a
backfill that was absent from the baseline but economically belongs at or
before it, so the baseline becomes unavailable until a new daily baseline is
created. Only higher revisions with strictly later financial timestamps are
classified as forward lineage. D1 performs no finance, market, FX, position,
or liability delta calculation and is not connected to current reads; the
current minute workflow remains active pending R10-D2.

## Ephemeral strict current value

R10-D2 consumes, but does not mutate, a complete D1 daily baseline. A current
account state is the baseline native state plus journal roots whose revision is
above the account cutoff and whose financial timestamp is strictly after the
baseline and no later than the server-owned `asOf`. D1 backfills remain fatal;
future-dated roots remain excluded.

Calculation-version compatibility is owned by the coordinated snapshot version
module and is not a newest-available fallback. With no active import publication
fence, the reader accepts only the current version 3 graph. While at least one
accessible account is fenced by a `queued`, `running`, `retry_wait`, or `failed`
import, the explicit allowlist is exactly versions 2 and 3 so the last complete
v2 publication can remain readable during an incomplete v3 import. Version 1
and every unlisted future or historical version remain unavailable. The
exception changes only this root version gate: exact NetWorth/account graph,
manifest, lineage, market evidence, source-policy, active-account, and canonical
root validation all remain mandatory.

For bank, cash, and savings accounts the delta is signed Transaction evidence.
For broker, exchange, and crypto-wallet accounts the baseline quantity and
native cost state are advanced by the canonical movement rules. For credit
cards, loans, and mortgages the newest unambiguous eligible LiabilityBalance is
a replacement point, never an additive delta.

Historical net deposits, realized P/L, fees, and taxes preserve their persisted
baseline values and add only forward evidence converted at each event date.
Unrealized P/L is recalculated from reconstructed quantity/native cost and exact
current price/FX evidence. Current cash, investment value, and liability value
use current-as-of FX. Foreign-to-foreign presentation requires the exact direct
market pair and never creates a synthetic provider observation.

One reconstructed canonical state owns both a primary projection in
User.baseCurrency and a presentation projection in Account.currency. Only
primaries contribute to aggregate portfolio, dashboard, and ephemeral current
NetWorth. Current reads persist no AccountSnapshot or NetWorthSnapshot; their
displayed value may therefore be newer than the last persisted history point.
History remains the immutable NetWorthSnapshot series.
