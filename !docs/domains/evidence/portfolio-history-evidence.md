## Portfolio history read model

R7-A defines portfolio history as a read-only presentation over persisted
`NetWorthSnapshot`, not a replay of canonical transactions, investment events,
movements, Holdings, prices, or FX. Each public point copies the physical
timestamp, cash value, portfolio value as investment value, liabilities value,
and total net worth. The persisted User base currency selects the single
currency represented by the response; snapshots in a former or different
currency are neither mixed nor converted.

Every candidate point must have canonical naive UTC `TIMESTAMP(3)`, valid
granularity/source enums and calculation version, exact finite MONEY values,
nonnegative portfolio and liability values, and exact
`cash + portfolio - liabilities == totalNetWorth`. Cash and total net worth may
be negative. Any malformed selected evidence invalidates the complete read.
Identical timestamps with different finance also fail closed; identical
finance collapses by granularity priority and persisted ID.

History range selection uses one injected clock read and calendar-safe
boundaries. The immutable series is ascending and unique. At most 512 public
points are retained; larger series keep the first and last values and the last
persisted point of each deterministic UTC time bucket. Empty history is valid
and never creates a synthetic current point.

`NetWorthSnapshot` does not physically retain historical net deposits,
investment cost basis, or the authoritative manifest of AccountSnapshot IDs
that could prove those aggregates. R7-A therefore exposes none of those fields
and invents no reconstruction. It adds no schema or writer change.

R7-B consumes this exact generated contract through a thin authenticated Next
adapter and strict browser validation. The validated series remains user-level
when account selection changes, and its currency must equal the current Python
portfolio response currency. The chart selects only `netWorthValue` or
`investmentValue`; exact strings remain authoritative for visible tooltips, and
one presentation-only numeric conversion supplies the Recharts coordinate.
There is no inferred deposit/cost-basis baseline, FX conversion, TypeScript
aggregation, or synthetic current point. The old TypeScript history service is
not exported or reachable from the active browser workflow. R7 remains in
progress pending its final audit.

This aggregation has no database, authorization, snapshot selection, reader,
price/FX lookup, Holding read, endpoint, clock, or side effect. Empty input,
metadata mismatch, duplicate identity, corrupt structure, and aggregate
overflow fail closed.

5L-E projects exactly one complete 5L-D aggregate into an immutable dashboard
snapshot. Its summary copies the aggregate values and adds only the structural
`assets = cash + investment` value. One canonical account card is emitted per
account. Investment positions are grouped by Asset type and also retained as
separate account-scoped entries in the global ranking; matching listings or
assets in different accounts are never merged.

Asset-type and position allocations use aggregate investment value as their
denominator. They do not reuse each position's account-local allocation, and
every derived percentage must be exactly representable as PERCENTAGE
`NUMERIC(8,4)` without rounding repair. Liabilities remain positive summary
magnitudes, not positions. A liability-only or zero-investment dashboard has
empty allocation and position-ranking tuples.

The 5L-E projection reads no database, authorizes no user, selects no snapshot,
and performs no Holding, price, or FX lookup. It adds no endpoint and cannot
derive historical change, performance, or trend from its single snapshot.
Public portfolio/dashboard orchestration is owned by 5L-F; historical dashboard
series remain outside 5L-E.

5L-F makes the complete 5L-D and 5L-E models public through two read-only POST
operations. Their shared request contains exact timestamp, granularity, output
currency, calculation version, and a non-empty explicit account selector tuple.
An optional snapshot ID guards lineage for its account. The API does not
discover memberships, choose a latest snapshot, infer currency or time, or
fall back to another immutable row.

One shared authorized exact-account reader applies the existing
owner/admin/editor/viewer access policy and delegates once per selector to
5L-B. The multi-account service resets the authentication transaction, sets
`REPEATABLE READ` as the first statement of one new transaction, and performs
every access check and exact graph read inside it in canonical account order.
It returns nothing unless every selector succeeds, then invokes 5L-D exactly
once. The dashboard service invokes that portfolio service and 5L-E exactly
once without another transaction or financial calculation.

Portfolio responses retain account-scoped 5L-A positions, native evidence, and
account-local allocation. Dashboard responses contain only the 5L-E aggregate
presentation and its global allocation. All financial Decimal values are JSON
strings; timestamps preserve milliseconds without adding timezone evidence.
User, membership, internal item lineage, persistence audits, and market-source
IDs remain private. The pre-existing legacy and exact single-account endpoints
remain unchanged, and historical dashboard series are still not modeled.

The final 5L cross-boundary audit adds no domain or production behavior. It
permanently verifies that the exact AccountSnapshot identity and persisted
item/listing/asset graph survive unchanged through the single-account view,
multi-account contribution, dashboard summary, and public serialization
boundaries. Exact Decimal sums, liability signs, account-local and global
allocation denominators, supported and rejected account shapes, deterministic
ordering, generic failures, and leakage exclusions are tested together.

PostgreSQL event evidence proves that single-account, multi-account, and
dashboard requests each use one isolation-first `REPEATABLE READ` financial
transaction after authentication, perform no write or lock, and leave the
session idle. Concurrent changes cannot create a mixed account perspective.
The physical exact-snapshot unique constraint and reader-level duplicate
candidate rejection are both independently covered.

Amounts in persistent financial models use PostgreSQL numeric types and Python
`Decimal`. Converting to floating point is currently limited to the temporary
portfolio response contract. New calculation code must keep `Decimal` through
calculation and define currency and rounding explicitly.

For account snapshots, all aggregate values—including cash, investment value,
cost basis, net deposits, P&L, fees, taxes, and total value—belong in one
explicit output currency. The internal writer can persist an explicitly
requested canonical output currency, and manual orchestration accepts that
currency as one optional exact request field. Omission still selects the
account's main currency. The accompanying `*ByCurrency` JSON fields preserve
their native-currency breakdown. Event-date FX is required for deposited and
invested values; a live value should start from the latest daily snapshot and
only apply later events.

The 5I-A Python contract, extended by pure 5K-C1, calculates an exact account
valuation from explicit caller-selected evidence. It validates an already
aligned UTC bucket, complete Holding and selected-price identity, direct
`native -> output currency` FX, account-type-specific cash or
positive-liability evidence, physical numeric representability, and 0–100 item
allocation. Persisted Account currency and requested output currency remain
separate validated metadata. It emits immutable, sorted valuation and
native-currency breakdown tuples without I/O.

Required rates are determined only by actual price, Holding cost, cash, and
liability evidence currencies. Same-output-currency values use exact identity
conversion without an FX row. Every other amount requires one supplied direct
rate to output currency; inverse rates, multi-hop chains, and fallback through
Account currency are never inferred. All supplied rates must be consumed, so
an empty mixed-currency account needs no synthetic rate and unrelated evidence
fails closed. Investment, cash, and positive-liability aggregates use output
currency while their breakdowns remain native. A liability observation must
still use Account currency, even when its scalar value is converted to a
different output currency.

The read-only 5K-C2 evidence command optionally requests that distinct output
currency. `None` resolves to persisted `Account.currency`, preserving every
existing writer caller. Explicit metadata owns only output currency; the
persisted Account independently owns account currency and supported
account-type/archive state. No User or membership evidence participates in
this internal boundary.

Persisted direct candidates are queried only for actual current price, Holding
cost, cash, liability, and historical metric currencies. Current valuation
selects the latest unambiguous direct row through the snapshot timestamp.
Lifetime net deposits, realized P/L, fees, and taxes independently select the
latest direct row through each evidence event timestamp. Snapshot-rate and
historical-rate IDs are audited separately and contain only consumed evidence.
There is no inverse, chain, bridge currency, source priority, or Account-currency
fallback.

Canonical liabilities remain positive observations in Account currency. When
output differs, 5K-C2 selects one latest direct Account-currency-to-output rate,
converts only through 5K-C1, and preserves the native liability breakdown plus
observation identity. Empty mixed-currency accounts require no rate.

The pure 5K-C3 physical projection persists `valuation.currency` as
`AccountSnapshot.currency`; it never derives output currency from Account
metadata. All physical scalar values use that currency. Snapshot UUIDv5
identity remains `(accountId, timestamp, currency, granularity)`, and each item
identity remains `(snapshotId, listingId)`, so otherwise equal projections in
different output currencies are physically distinct.

Investment item native price, value, and cost fields remain in their evidence
currencies. Converted value and cost fields use snapshot currency, native
breakdowns remain fixed-scale JSON, and consumed direct rates use the existing
version-1 audit object. For liabilities, the projection requires one native
breakdown and either no rate for same-currency evidence or exactly one direct
native-to-output rate whose exact multiplication equals the positive converted
liability scalar. An explicit zero observation remains evidence and still
requires that direct rate when currencies differ.

`AccountSnapshot` has no liability-native-breakdown column. 5K-C3 therefore
validates that native evidence without hiding it in another JSON field, while
retaining the liability observation identity in the nonphysical persistence
audit. No schema or ORM change is required.

The 5K-C4 writer resolves an optional command output currency after locking and
validating the persisted Account. `None` preserves Account-currency behavior.
The resolved output currency is part of the complete physical identity used by
the existing SHA-256 advisory-lock scope, the evidence command, projected-row
validation, and the exact replay query. The projection must also match all
command-owned source, version, timestamp, and recalculation metadata before
replay or insertion. Different output currencies therefore coexist and replay
independently under distinct deterministic snapshot and item IDs.

Investment writes retain canonical ledger/Holding locks and compatible market
table `SHARE` locks. Liability writes take a `LiabilityBalance` table `SHARE`
lock before evidence selection; mixed-currency liability writes also take the
market lock before direct FX selection. Concurrent observation or FX inserts
cannot split a single physical write across evidence states. The writer still
owns one outer transaction, and changed evidence for an existing identity
conflicts without overwrite or repair.

The 5K-C5 manual endpoint exposes that optional writer field without changing
the route or response. No body, `{}`, JSON null, and an explicit null preserve
`None`; an explicit `outputCurrency` must be exactly three uppercase ASCII
letters. The API rejects normalization, non-string input, and extra fields
before the service. The service repeats the invariant for direct internal
calls, preserves owner/admin/editor authorization and concealed inaccessible
accounts, closes the authorization transaction, captures one minute bucket,
and invokes the writer once.

No User lookup participates in this account operation:
`User.baseCurrency` is never an implicit fallback. Omitted output currency
resolves to persisted `Account.currency`; explicit Account currency replays the
same identity, and a distinct currency creates or replays its own physical
identity. Missing FX remains a generic unavailable conflict with no rate or
currency-pair disclosure. Coordinated User-base-currency execution remains
5K-D.

The contract deliberately does not claim a persistable `AccountSnapshot`.
Complete net-deposit, realized/unrealized P&L, fee, and tax evidence is not yet
adopted by the pure boundary; database defaults are not treated as financial
proof and these values are not silently zeroed. Price/FX selection, JSONB
serialization, persistence metadata, writer/orchestration, and all
`NetWorthSnapshot` work remain later steps.

The 5I-B adapter selects the latest unambiguous persisted price per open
listing and direct `native -> account currency` FX. Snapshot valuation uses
snapshot-as-of FX; lifetime net deposits, explicit realized P/L, outgoing fee,
and outgoing tax evidence use event-as-of FX. Bank/cash/savings balance is the
active signed Transaction history; investment cash is the active canonical
cash/fee/tax movement history. Liability accounts consume one exact latest-as-of
5I-L1 `LiabilityBalance` observation in Account currency. Asset transfers
remain fail-closed for net-deposit metrics because counter-account
identity is not persisted. The adapter returns immutable evidence, never writes
`AccountSnapshot`, and leaves coherent locking plus persistence to 5I-D.

`TransactionType` and `TransactionClassification` do not persist explicit
external-deposit, external-withdrawal, bank-fee, tax, interest, or dividend
semantics. Consequently, ordinary income/expense and transfer classifications
may affect a cash-account balance but cannot prove net deposits, fees, or taxes.
Those metrics use an explicit unsupported result variant, not zero; descriptions,
categories, counterparties, notes, amount signs, and account type are never used
to infer them. The 5I-C physical projection rejects unsupported metrics instead
of mapping them to the physical column defaults. Investment value, cost basis, and
unrealized investment P/L are structurally zero for bank/cash/savings because
these account types cannot contain Holdings under the snapshot contract.
Realized investment P/L remains unsupported: the physical schema does not
constrain InvestmentEvent ownership by Account type, so absence of a Holding
does not prove a lifetime realized-P/L zero.

Supported 5I-B account types are bank, cash, savings, broker, exchange, crypto
wallet, credit card, loan, and mortgage. For the non-liability types, liability
is structurally impossible in the
account-type snapshot contract, so the exact liability aggregate is zero and
its native breakdown is empty. This must not be confused with an unknown
liability balance. Credit-card, loan, and mortgage accounts require one
unambiguous eligible canonical observation; missing evidence never becomes
zero.

`LiabilityBalance` stores positive amounts owed for credit-card, loan, and
mortgage accounts. Principal, accrued interest, fees outstanding, and total
use exact `NUMERIC(18,6)`, remain nonnegative, and satisfy
`total = principal + interest + fees`. Currency must match the Account.
Latest-as-of selection uses the maximum `effectiveAt` not after the requested
timestamp and requires exactly one row at that timestamp; missing, ambiguous,
future-only, malformed, or archived-account evidence fails without a zero
fallback. The read-only selector owns no transaction and writes no snapshot.
Account-type validation is application-owned because a cross-table PostgreSQL
`CHECK` would be misleading. The 5I-L2A writer appends one exact deterministic
observation in its own outer transaction. It locks the Account and both
physical identity domains, returns an exact replay only when every physical
field (including deterministic ID and created timestamp) matches, and rejects
all differences without update or repair. 5I-L2B consumes selected observations
in authorized manual snapshots; public liability authorization/import remains
deferred.

The pure 5I-C adapter maps exact 5I-B evidence to every physical snapshot and
item column without ORM construction or database access. Snapshot identity is
deterministic by account, millisecond timestamp, output currency, and
granularity; item identity is deterministic by snapshot and listing. JSONB
currency breakdowns use sorted uppercase keys and fixed-scale decimal strings.
An empty exact breakdown is `{}`, while an unavailable native breakdown is
`null`. The versioned exchange-rate audit stores full consumed snapshot-rate
evidence and selected historical rate IDs. Selected price IDs remain immutable
non-row audit metadata because the physical schema has no price-evidence
column. The physical schema likewise has no liability-breakdown column.

For a liability account, the 5I-L2B physical contract is a zero-item snapshot:
cash, investment value, and investment cost basis are zero;
`liabilitiesValue` is the positive selected `totalOutstanding`; and
`totalValue = -liabilitiesValue`. Because 5I-L1 requires observation currency
to equal Account/snapshot currency, the scalar is complete despite the absent
breakdown column. Selected balance ID, effective timestamp, and source remain
immutable non-row audit metadata. An explicit zero observation means fully
repaid; missing, future-only, ambiguous, or corrupt evidence fails.

The internal 5I-D writer owns one outer transaction for one immutable command.
It locks account metadata and the exact snapshot identity. Investment accounts
then lock all compatible account/source canonical history scopes, canonical
rows, current Holdings and their Listing/Asset evidence, and take compatible
`SHARE` locks over price and FX tables before 5I-B selection. Liability
accounts skip those unrelated locks. Their observations are append-only and
5I-L1 loads all eligible rows in one SQL statement, so `READ COMMITTED` sees
one complete old or new evidence set rather than mixed components.
It then builds the 5I-C plan and inserts, flushes, reloads, and validates the
complete physical graph. Exact state is a read-only replay; any physical or
evidence difference is a conflict with no update, delete, upsert, or repair.
The 5I-E public boundary added authenticated manual recalculation; 5K-C5 later
added its optional output-currency body without changing the operation.
Owner, admin, and editor memberships are allowed; viewer, foreign, missing,
and archived accounts share a concealed 404 contract. The server
captures one deterministic minute bucket and owns source, granularity,
calculation version, recalculation flag, and all timestamps. Created and exact
replay outcomes use one stable HTTP 200 response without financial evidence.
Authorization lookup completes before the writer receives an idle session, and
the writer revalidates Account state under lock. Membership revocation in the
narrow interval between request-time authorization and writer commit remains a
documented non-atomic boundary.

The 5J-A net-worth contract is a pure user-level aggregation of a complete,
coherent tuple of exact AccountSnapshot evidence. It currently accepts broker,
exchange, crypto-wallet, credit-card, loan, and mortgage snapshots; bank, cash,
and savings fail rather than being omitted. Every snapshot must use the same
exact bucket timestamp, granularity, and output currency, and account and
snapshot identities must be unique. Each Account currency remains canonical
but may differ from the already-converted snapshot/output currency; 5J-A never
selects FX or performs conversion.

For each account, assets are signed cash plus nonnegative investment market
value, positive liability is subtracted, and the result must equal the persisted
account `totalValue`. Across the user, `assets = cash + portfolio`,
`net worth = assets - liabilities`, and that result must also equal the sum of
all account totals. Negative investment cash reduces assets without becoming a
liability. Explicit zero debt remains a counted liability account.

Scalar values and their intermediate aggregates use exact MONEY
`NUMERIC(18,6)` Decimal semantics. Native cash and liability breakdowns also
use MONEY, while native portfolio and total-net-worth breakdowns use QUANTITY
`NUMERIC(28,10)`. The total-native contract preserves portfolio precision when
calculating cash plus portfolio minus liability; there is no rounding or
truncation. Native breakdowns are preserved only when complete; unavailable
evidence remains distinct from an empty exact breakdown. An unavailable
nonnegative portfolio or liability breakdown with an exact zero scalar may act
as a neutral total-native contribution without changing its category output
from `None`; any nonzero unavailable amount still makes the total unavailable.
5J-A performs no database selection, FX conversion, persistence,
authorization, or scheduling.

The read-only 5J-B adapter proves the complete current user/account coverage
through persisted `AccountMember` rows. Validly archived accounts are excluded;
the schema has no historical activation intervals, so historical membership or
archive reconstruction is not claimed. Any active bank, cash, or savings
account invalidates the whole result. Every supported account requires exactly
one physical AccountSnapshot at the requested timestamp, granularity, currency,
and calculation version.

5J-B validates persisted ownership, financial scalars, and canonical fixed-scale
JSONB breakdowns, then invokes 5J-A once. AccountSnapshot has no physical
liability-breakdown column, so that optional native evidence remains
unavailable rather than inferred. The adapter requires a caller-owned
`REPEATABLE READ` or `SERIALIZABLE` transaction; it rejects `READ COMMITTED` and
owns no transaction or write.

The pure 5J-C contract maps that complete evidence to every physical
`NetWorthSnapshot` field. Snapshot identity is a deterministic UUIDv5 over the
physical unique key `(userId, timestamp, currency, granularity)`. Scalar
financial values remain exact MONEY; native JSONB values use fixed-scale
strings with MONEY precision for cash/liability and QUANTITY precision for
portfolio/total. Unavailable breakdowns persist as SQL NULL and exact empty
breakdowns as `{}`. `exchangeRates` is NULL because 5J performs no FX
conversion.

5J-C validates the native categories before serialization and rederives total
native net worth as cash plus portfolio minus liabilities using QUANTITY for
every intermediate operation. The supplied total must match exactly,
including `None` versus an exact tuple, currencies, deterministic order,
amounts, signs, and zero entries. Unavailable cash always propagates to an
unavailable total. Unavailable portfolio or liability evidence is neutral
only when its scalar is exactly zero and remains SQL NULL in its own physical
field; nonzero unavailable evidence makes the total unavailable. The
rederivation performs no FX conversion and never rounds or drops a
cancellation-to-zero currency.

Selected account and AccountSnapshot identities are revalidated against every
projection contribution and returned only as immutable ephemeral audit
metadata. The physical schema has no source-snapshot lineage columns, so 5J-C
does not hide those IDs in unrelated JSON. It creates no ORM model and performs
no database access.

The 5J-D writer is the sole transaction owner for one internal net-worth write.
It starts every attempt at PostgreSQL `SERIALIZABLE`, then takes a
transaction-scoped advisory lock namespaced by the full physical snapshot key.
5J-B evidence and the 5J-C row are rebuilt once inside each attempt before any
target-row decision. Different users and timestamps use different locks.

An existing target row is replayed only when all 19 physical values match the
new exact projection. This includes deterministic ID, financial scalars,
source, calculation version, persistence timestamps, recalculation flag,
fixed-scale JSON strings, and SQL NULL versus exact empty JSON. A difference
or deterministic-ID collision fails closed; no existing net-worth snapshot is
updated, repaired, replaced, or upserted.

A new target is inserted once, flushed, reloaded, and compared in full before
commit. Failure rolls back the attempt without changing source Users,
Accounts, memberships, AccountSnapshots, or AccountSnapshotItems. PostgreSQL
serialization failure, deadlock, or concurrent unique violation retries the
entire transaction at most three times; all evidence, projection, validation,
conflict, and other SQL failures remain single-attempt failures. Persisted
source-snapshot lineage is still unavailable without an intentional future
schema change. Public authorization and orchestration are owned by 5J-E.

The 5J-E manual operation authorizes only the authenticated principal and
derives the snapshot currency from that principal's persisted
`User.baseCurrency`. It closes the authentication read transaction before
entering 5J-D, while 5J-B reloads and revalidates the same currency inside the
new SERIALIZABLE transaction. The public minute bucket is the single timestamp
for identity, calculation, and creation metadata, making unchanged same-minute
requests exact replays.

Manual net-worth recalculation requires one already-persisted exact
`AccountSnapshot` for every current active supported account. Missing evidence
fails the whole user projection; no account is omitted and no source snapshot
is created. The response deliberately excludes user identity, account/source
snapshot lineage, JSON evidence, and financial values. Scheduled generation,
automatic account-snapshot orchestration, and historical net-worth reads remain
unimplemented.
