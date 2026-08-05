# Domain Model

The PostgreSQL schema contains 31 application tables. SQLAlchemy has a complete
mirror of that physical schema; this does not mean every domain has an API or
application service yet.

| Domain                 | Canonical records                                                      | Derived/read records                                         | Current Python use                                                                  |
| ---------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| Identity and access    | `User`, `AccountMember`, `AccountInvite`                               | —                                                            | Implemented                                                                         |
| Accounts               | `Account`                                                              | —                                                            | Implemented                                                                         |
| Liabilities            | `LiabilityBalance`                                                     | latest-as-of liability evidence                              | Read-only selection and atomic internal writer                                      |
| Cash transactions      | `Transaction`, `TransactionPair`, `TransactionSplit`                   | —                                                            | Schema only                                                                         |
| Classification         | `Counterparty`, `CounterpartyAlias`, `Category`, `CategoryRule`        | —                                                            | Schema only                                                                         |
| Budgets                | `Budget` and related item/account/alert tables                         | —                                                            | Schema only                                                                         |
| Assets and market data | `Asset`, `AssetListing`, `AssetAlias`, `PriceSnapshot`, `ExchangeRate` | exact requirements, CNB FX, CoinGecko, Twelve Data identity  | R5-B2B0 identity implemented; Twelve Data HTTP evidence remains planned             |
| Investment ledger      | `InvestmentEvent`, `InvestmentMovement`                                | —                                                            | Schema only                                                                         |
| Portfolio              | —                                                                      | `Holding`                                                    | Read by portfolio; deterministic rebuild and authorized manual endpoint implemented |
| Imports                | `ImportBatch`, `ImportRow`, `ImportLog`                                | parse, normalization, and duplicate state                    | Implemented through duplicate detection                                             |
| Snapshots              | —                                                                      | `AccountSnapshot`, `AccountSnapshotItem`, `NetWorthSnapshot` | 5I account persistence and 5J-A pure net-worth projection                           |

## Exact market evidence

R5-A uses the existing physical market tables without adding a schema object.
`PriceSnapshot.price` remains `NUMERIC(28,10)`,
`ExchangeRate.rate` remains `NUMERIC(18,8)`, and both evidence timestamps
remain naive UTC `TIMESTAMP(3)`. Provider adapters must return already
canonical, positive, finite Decimal values at those exact physical scales.
Validation never rounds, repairs, takes an absolute value, converts through
`float`, or changes a currency direction.

A price requirement identifies one persisted Account, Asset, Listing, Listing
currency, provider source, provider symbol, and `through` timestamp. An active
nonzero Holding uses its exact Listing provider identity when that source is
registered. Otherwise it may use exactly one supported AssetAlias belonging to
the same Asset. Missing or multiple supported aliases are unavailable or
ambiguous; symbols, names, account type, or primary-listing flags never infer a
provider identity.

FX requirements always describe one direct
`from_currency -> output_currency` pair. Current requirements cover account,
cash, Listing-price, Holding cost-basis, and liability currencies at the
snapshot timestamp. Historical requirements use the timestamp of the
persisted Transaction, InvestmentEvent, or related canonical movement amount.
They never substitute snapshot-time FX for event-date FX. Same currency is a
structural bypass, not an `ExchangeRate` row; inverse and cross rates are not
derived in R5-A.

The explicit 0.1 freshness policy is 72 hours for prices and seven calendar
days for FX. Evidence exactly at the maximum age is valid; future or older
evidence fails closed. Snapshot evidence selection applies this same policy to
current price, current FX, and historical event-date FX. Missing or stale
evidence therefore creates neither a partial AccountSnapshot nor a partial
NetWorthSnapshot.

R5-B1 supplies the first production source without changing this model. The
production FX registry contains exactly the CNB adapter. CNB requirements are
limited to direct
`foreign currency -> CZK` pairs. One official daily XML document is requested
for the exact requirement date; there is no inverse, cross, alternate-source,
current-date, or previous-date lookup. The source document publication date,
not request time, becomes the evidence timestamp. An older weekend or holiday
publication must still satisfy the shared seven-day freshness policy.

CNB publishes a CZK value for an explicit currency amount. The canonical
`ExchangeRate.rate` is their exact Decimal quotient. Parser locale rules,
currency uniqueness, positive finite values, and the `NUMERIC(18,8)` boundary
are fail-closed; no rounding or `float` conversion is permitted.

Market evidence persistence is append-only. Price UUIDv5 identity is based on
Listing, observation timestamp, and source; FX UUIDv5 identity is based on the
direct pair, effective timestamp, and source. Price, rate, creation time, User,
Account, and randomness are excluded from those identities. Exact persisted
state replays without a write. A different value under the same identity is a
conflict, and the single mixed price/FX batch rolls back completely. R5-A
defines provider ports. R5-B1 PostgreSQL tests use mocked CNB HTTP responses
with the real production registry, R5-A service, and writer; they add no direct
rate or price rows.

R5-B2A adds exactly one production price source, CoinGecko, without changing
the physical model. A requirement is eligible only through one persisted exact
`AssetAlias(provider=coingecko, externalId=<CoinGecko ID>)`; Listing tickers,
Asset names, `/coins/list`, and hard-coded symbol mappings are not identities.
The provider's positive exact Decimal and actual `last_updated_at` UTC time are
validated by R5-A and persisted append-only as `PriceSnapshot`. The timestamp
is not clamped, and overprecision is not rounded. Anycoin crypto assets without
that alias fail before HTTP; Trading212 listed securities remain for R5-B2B1.
PostgreSQL tests use mocked HTTP but the production factory, planner, writer,
snapshot executor, and exact portfolio/dashboard readers. Public
market-evidence orchestration remains assigned to R5-B3, so overall R5 remains
in progress.

R5-B2B0 extends the two existing provider-identity enums with the exact value
`twelve_data`. An `AssetAlias(provider=twelve_data, externalId=...)` stores one
opaque provider-owned identity; the planner never derives it from a
Trading212 symbol, Asset symbol, ISIN, name, exchange, MIC, or another alias.
When a matching provider is injected, that unchanged string becomes the
requirement's provider symbol. Production price composition does not yet
register Twelve Data, so the same requirement is unavailable before HTTP.

The Stooq candidate was rejected because the reviewed public surface did not
establish an authoritative API and quote-time timezone contract. Twelve
Data's official time-series contract documents exchange timezone metadata and
IANA timezone behavior, which allows R5-B2B1 to define a fail-closed timestamp
conversion. R5-B2B0 adds no HTTP client, API key, observation, price row,
endpoint, alias writer, or identity-format parser; overall R5 remains in
progress.

The fixed UUIDv5 namespaces are
`8c46da0b-b09a-49c7-94f1-a510cf4c2f7c` for `PriceSnapshot` and
`93484f65-330c-47e9-a592-49e4fd9a5122` for `ExchangeRate`. Changing either
value is an identity-contract change, not an implementation detail.

## Important relationships

- A user can access an account through an account membership. The creating user
  receives the immutable `owner` membership.
- An account has a three-letter main currency. It is the display and storage
  currency for account-level aggregates, not a global hard-coded currency.
- Assets may have several listings; a holding is unique per account and listing.
- An investment event is the high-level historical action. Its movements are
  the atomic asset, cash, fee, and tax legs.
- Import batches belong to a user and account and are unique by their SHA-256
  checksum within that pair. Rows preserve raw data, validation state, and a
  candidate deduplication key. Duplicate detection preserves already imported
  history and otherwise keeps the earliest eligible row for a key within an
  account and source.
- Holdings and snapshots are rebuildable read models. They must never replace
  transactions or ledger events as the historical source of truth.

The Python holdings domain has pure deterministic contracts that validate and
aggregate active canonical `InvestmentMovement` quantity and produce exact
weighted-average persistence fields by `(accountId, listingId)`. Its internal
caller-transaction-owned rebuild writer explicitly locks canonical history,
relations, and current Holdings, then atomically creates, updates, or deletes
the complete account projection. Unsupported evidence and persisted corruption
fail closed. The public account-scoped rebuild boundary allows persisted
owner/admin/editor memberships, locks the calling membership through commit,
and returns only aggregate rebuild counts. Viewer, foreign, removed, and
archived access is rejected without mutation. Replay remains read-only and
automatic post-import rebuild remains deferred.

## Money and snapshot invariants

### Pure portfolio snapshot presentation contract

Step 5L-A adds a single-account portfolio presentation contract over complete,
already validated immutable AccountSnapshot evidence. The AccountSnapshot graph
is the sole financial authority: the projection does not read Holdings,
InvestmentEvents, Movements, prices, or exchange rates and does not recalculate
cost basis, P/L, FX, or missing data. Every financial input and output remains a
`Decimal`; `MONEY NUMERIC(18,6)`, `QUANTITY NUMERIC(28,10)`,
`PERCENTAGE NUMERIC(8,4)`, and naive `TIMESTAMP(3)` limits are validated without
rounding.

The view currency is the snapshot output currency. Every converted position
value and cost uses that currency, while Account currency, price currency,
native value currency, and native cost currency remain explicit independent
fields. The projection verifies exact snapshot formulas, item sums, item and
aggregate unrealized P/L, and the already persisted allocation definition.
Positive investment portfolios require exact allocations equal to
`position.value / investment_value * 100` and an exact total of 100; zero-value
positions and zero portfolios require zero allocation.

Broker, exchange, and crypto-wallet snapshots can expose positions. Credit-card,
loan, and mortgage snapshots expose summary-only liability views with positive
liability magnitude, negative total value, structural-zero investment values,
and no positions. Bank, cash, and savings remain unavailable because their
AccountSnapshot persistence contract is not supported. Positions are
canonically ordered by `(asset_type, symbol, listing_id, item_id)`; duplicate
item, listing, or asset/listing identities fail closed.

5L-B adds a read-only adapter for one exact persisted AccountSnapshot identity.
It requires a caller-owned `REPEATABLE READ` or `SERIALIZABLE` transaction,
loads only Account, AccountSnapshot, AccountSnapshotItem, AssetListing, and
Asset rows, and fails closed on missing, ambiguous, corrupt, or relationally
incomplete evidence. It performs no latest-snapshot selection, price or FX
lookup, live-Holding calculation, fallback, write, or lock.

Physical AccountSnapshotItem `valueCurrency` is native price/value evidence and
must equal its `priceCurrency` and AssetListing currency. The pure 5L-A
position `value_currency` is the parent AccountSnapshot output currency, while
the physical item `costCurrency` must already equal that output currency. The
item unrealized P/L supplied to 5L-A is only the exact Decimal subtraction of
the persisted value and cost basis; no cost basis, FX, or valuation is
recalculated.

5L-B adds no authorization, User or membership selection, endpoint, dashboard,
multi-account aggregation, schema change, or migration.

5L-C exposes the pure view at
`GET /api/v1/portfolio/accounts/{account_id}/snapshot`. Owner, admin, editor,
and viewer memberships may read one exact account snapshot; foreign, missing,
and archived accounts are not disclosed. Authorization and the 5L-B reader run
inside the same fresh `REPEATABLE READ` transaction after the authentication
read transaction is closed.

The response retains the output/native currency split and serializes every
financial Decimal as a JSON string. It excludes internal snapshot-item lineage,
User and membership data, persistence timestamps, and JSONB audit evidence.
5L-C performs no financial, allocation, cost-basis, P/L, liability, price, or
FX calculation and reads no live Holding, PriceSnapshot, or ExchangeRate. The
existing basic portfolio endpoint still reads live Holdings and latest stored
FX and remains a temporary unchanged legacy reader.

5L-D is a pure multi-account presentation aggregate over non-empty tuples of
already complete 5L-A views. Every contribution must share timestamp,
granularity, output currency, and calculation version; account and snapshot
identities are unique. Different Account currencies, account types, snapshot
sources, and native position currencies remain valid.

Accounts use canonical `(accountId, snapshotId)` order. Positions remain nested
under their source account in the existing 5L-A order, so matching assets,
listings, or symbols across accounts are not merged. Aggregate financial fields
are exact Decimal sums and must remain inside MONEY `NUMERIC(18,6)`. The
aggregate rechecks only total-value, unrealized-P/L, account-count, and
position-count invariants; it does not duplicate per-account or per-position
valuation rules.

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

## Coordinated snapshot-refresh plan

The pure 5K-A contract describes a complete coordinated refresh without
executing it. Current active broker, exchange, crypto-wallet, credit-card, loan,
and mortgage accounts each produce one immutable target. An active bank, cash,
or savings account invalidates the complete plan. A consistently archived
account is excluded from current-state coverage; contradictory archive fields
fail closed. An empty active set is valid and still yields a final net-worth
target.

Membership capability remains explicit: owner, admin, and editor may refresh an
account snapshot; viewer may only reuse an exact existing snapshot. The latter
is not a write grant. Every target uses the User base currency as its required
output currency while retaining the Account currency. Different currencies
mean exact FX evidence will be required later, but 5K-A neither selects nor
applies FX.

The final net-worth target contains every active account identity in
deterministic order and depends on exact AccountSnapshots sharing its timestamp,
granularity, output currency, and calculation version. It cannot run until all
write-capable and reuse-only targets are satisfied. This is only a declarative
dependency: 5K-A reads no database state, invokes no writer, and performs no
financial calculation. 5K-C1 establishes pure calculation, 5K-C2 read-only
persisted evidence selection, 5K-C3 pure physical projection, and 5K-C4
output-currency writer identity, locking, and replay. 5K-C5 exposes optional
manual output currency. Mixed-currency coordinated execution remains 5K-D.

The read-only 5K-B boundary turns persisted current state into immutable
coverage evidence. The persisted User exclusively supplies the output/base
currency, while each persisted AccountMember supplies role, relation, and
acceptance. Every joined row is retained for 5K-A validation; SQL does not
filter archived, unsupported, or incomplete evidence.

After one pure 5K-A call, owner/admin/editor targets remain future writer
targets regardless of existing rows. Viewer targets require exactly one
AccountSnapshot matching account, timestamp, granularity, User base currency,
and calculation version. Existing source and persistence timestamps are
structurally validated but source equality with the orchestration is not
required. The selected output contains only immutable account/snapshot
identities, never ORM or financial values.

This coverage proof is intentionally not financial validation. A structurally
eligible reused AccountSnapshot may still be financially corrupt, which must
fail later in the complete 5J-B validation. 5K-B requires coherent
`REPEATABLE READ` or `SERIALIZABLE`, owns no transaction or lock, disables
autoflush, and performs no write.

## Exact coordinated net-worth dependencies

5K-D is split into an exact dependency guard (5K-D1) and the later coordinated
executor (5K-D2). A guarded internal NetWorth write may declare one immutable,
unique, already sorted tuple of `(account_id, AccountSnapshot.id)` identities.
`None` means the existing manual selection of every current active supported
account; `()` means the exact current account set must be empty.

The guard is not a caller-selected account filter. Net-worth evidence still
loads the persisted User and complete current Account/AccountMember access set,
derives active supported accounts, and requires exact ordered account-ID
equality. It then selects the same-bucket, same-granularity, same-output-
currency, same-version AccountSnapshots and requires exact ordered pair
equality. Added, removed, archived, or same-count-substituted accounts and
replaced snapshot identities all fail closed.

The same tuple is checked in every SERIALIZABLE writer attempt and again
against the physical projection audit before replay or creation. It is returned
only in the internal writer result so 5K-D2 can compare completed refresh
outputs with final net-worth dependencies. It is not persisted in
NetWorthSnapshot, does not change physical identity, and is absent from the
manual HTTP request and response.

5K-D2 turns one exact 5K-B coverage result into a coordinated execution without
moving any financial rule into orchestration. Its initial caller-owned
`REPEATABLE READ` transaction establishes the complete current User, account,
membership, role, output-currency, and viewer-reuse set. The transaction closes
before any write. Every owner/admin/editor target then receives one independent
AccountSnapshot writer call; every viewer target contributes its already
persisted snapshot identity and never invokes that writer.

The combined immutable lineage is ordered by the plan's complete account set
and guarded by 5K-D1 during the final NetWorth write. Added, removed, archived,
or same-count-substituted access after coverage cannot produce a stale
NetWorthSnapshot. Each domain writer owns and commits its own transaction, so
successful account snapshots survive a later failure. Re-execution invokes all
refresh targets again and uses exact physical replay—not in-memory state—as the
only resume mechanism. No compensation, overwrite, repair, cross-stage outer
transaction, job-state model, or new persisted lineage is introduced. 5K-E1
and 5K-E2 are the implemented endpoint, authorization, and post-import
integration boundary.

## Authorized coordinated manual refresh

5K-E is decomposed into the 5K-E1 manual endpoint and 5K-E2
import/post-processing integration. E1 targets exactly the authenticated
principal's user and accepts no body, user/account IDs, currency, timestamp,
granularity, or lineage. One server clock value becomes a naive UTC minute
bucket used for all refresh timestamps after the authentication read
transaction has been committed and the shared session is idle.

The coordinated executor remains the source of persisted User base currency,
complete account coverage, refresh versus viewer reuse-only classification,
source AccountSnapshot lineage, and final guarded NetWorth creation. Since
5M-A, the public result also exposes the exact read manifest consisting of the
executor timestamp, granularity, output currency, calculation version, and
every validated `(account_id, snapshot_id)` identity in deterministic executor
order. This is the only public account/source lineage: when non-empty, it calls
the existing exact 5L portfolio and dashboard reads without another database
query, account discovery, latest selection, sort, or fallback.

Every successful non-empty manifest is directly compatible with both 5L
request contracts and is transported unchanged. A successful empty manifest
has exactly `accounts == []`, zero selected and account-snapshot counts, and
represents the explicit state that the user has no snapshot-capable account.
It is complete rather than partial and does not arise from an error, fallback,
or latest-snapshot lookup. The 5L endpoints continue to require a non-empty
account set, so 5M-B must return an explicit empty workflow state before either
5L call and must not discover accounts or manufacture a synthetic selector.

The result otherwise exposes only the NetWorth snapshot identity and
disposition plus aggregate execution counts. It never exposes user identity,
memberships, roles, refresh modes, writer dispositions, FX evidence,
projections, selected item identities, or audits. A partial or inconsistent
manifest and other missing/incomplete evidence use the generic unavailable
HTTP 409 contract; immutable conflict retains its distinct generic HTTP 409
contract, neither identifying the failing account.

Because each AccountSnapshot writer commits independently, an unavailable
response can coexist with valid completed account rows. The next identical
request resumes through exact replay and creates NetWorth only after all
required identities are complete. E1 introduces no compensation, persisted
execution state, migration, automatic retry, scheduler, worker, background job,
or background execution.

## Import post-processing outcome

`ImportBatchPostingService` now returns an internal immutable terminal result
that includes counts of imported Transaction and InvestmentEvent targets. Each
imported row must reference exactly one target and target counts must equal
`rowsImported`. These counts are orchestration evidence and are not public API
fields.

After that service commits, 5K-E2 may rebuild Holdings for an investment-event
batch and then refresh all snapshots reachable by the principal's current user.
The refresh uses source `import_event`, the common AccountSnapshot/NetWorth
calculation version, and a minute bucket derived from the persisted
`ImportBatch.completedAt`. Replaying the batch therefore reuses the same
Holding and snapshot identities.

`ImportPostResponse.snapshot_refresh_status` is a Python/API-only enum with
`created`, `replayed`, `not_required`, `unavailable`, and `conflict`. It does
not alter ImportBatch status and has no database enum. Known post-processing
failure leaves canonical imported rows and any committed Holding or
AccountSnapshot rows intact. ImportLog records generic deterministic audits,
not job progress. There is no compensation, migration, job table, scheduler,
worker, queue, or background task.

## Final coordinated-refresh audit

The completed 5K audit confirms the end-to-end persisted coverage, valuation,
physical projection, writer, lineage, manual-entry, and import-entry
contracts. Physical AccountSnapshot identity remains
`(accountId, timestamp, output currency, granularity)` and NetWorthSnapshot
identity remains `(userId, timestamp, currency, granularity)`. The same minute
reached through manual and import orchestration never creates an alternate
timestamp: exact metadata replays, while different immutable source or
recalculation metadata conflicts without update, delete, or repair.

Role-mixed coverage still writes owner/admin/editor targets, reuses viewer
targets only from exact persisted evidence, and sends the complete ordered
lineage to the final SERIALIZABLE NetWorth guard. Partial account-stage
commits remain replayable after a later failure. E1 reports state/conflict as
generic HTTP 409; E2 preserves the committed import and reports the same known
outcomes as HTTP 200 `snapshot_refresh_status`. Neither response exposes
account/source lineage, FX evidence, financial breakdowns, or internal
exceptions.

The physical PostgreSQL catalog retains naive `TIMESTAMP(3)`, canonical
numeric scales, JSONB audits, existing foreign-key delete behavior, and
currency-sensitive unique indexes. No 5K migration, job-state table,
scheduler, worker, queue, background task, compensation path, or support for
bank/cash/savings AccountSnapshots was introduced.
