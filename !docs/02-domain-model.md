# Domain Model

The PostgreSQL schema contains 31 application tables. SQLAlchemy has a complete
mirror of that physical schema; this does not mean every domain has an API or
application service yet.

| Domain                 | Canonical records                                                      | Derived/read records                                         | Current Python use                            |
| ---------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| Identity and access    | `User`, `AccountMember`, `AccountInvite`                               | —                                                            | Implemented                                   |
| Accounts               | `Account`                                                              | —                                                            | Implemented                                   |
| Liabilities            | `LiabilityBalance`                                                     | latest-as-of liability evidence                              | Read-only selection and atomic internal writer |
| Cash transactions      | `Transaction`, `TransactionPair`, `TransactionSplit`                   | —                                                            | Schema only                                   |
| Classification         | `Counterparty`, `CounterpartyAlias`, `Category`, `CategoryRule`        | —                                                            | Schema only                                   |
| Budgets                | `Budget` and related item/account/alert tables                         | —                                                            | Schema only                                   |
| Assets and market data | `Asset`, `AssetListing`, `AssetAlias`, `PriceSnapshot`, `ExchangeRate` | prices and FX                                                | FX is read by portfolio                       |
| Investment ledger      | `InvestmentEvent`, `InvestmentMovement`                                | —                                                            | Schema only                                   |
| Portfolio              | —                                                                      | `Holding`                                                    | Read by portfolio; deterministic rebuild and authorized manual endpoint implemented |
| Imports                | `ImportBatch`, `ImportRow`, `ImportLog`                                | parse, normalization, and duplicate state                    | Implemented through duplicate detection       |
| Snapshots              | —                                                                      | `AccountSnapshot`, `AccountSnapshotItem`, `NetWorthSnapshot` | 5I account persistence and 5J-A pure net-worth projection |

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

Amounts in persistent financial models use PostgreSQL numeric types and Python
`Decimal`. Converting to floating point is currently limited to the temporary
portfolio response contract. New calculation code must keep `Decimal` through
calculation and define currency and rounding explicitly.

For account snapshots, all aggregate values—including cash, investment value,
cost basis, net deposits, P&L, fees, taxes, and total value—belong in the
account's main currency. The accompanying `*ByCurrency` JSON fields preserve
their native-currency breakdown. Event-date FX is required for deposited and
invested values; a live value should start from the latest daily snapshot and
only apply later events.

The 5I-A Python contract calculates an exact account valuation from explicit
caller-selected evidence. It validates an already aligned UTC bucket, complete
Holding and selected-price identity, direct `base -> account currency` FX,
account-type-specific cash or positive-liability evidence, physical numeric
representability, and 0–100 item allocation. It emits immutable, sorted
valuation and native-currency breakdown tuples without I/O.

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
The 5I-E public boundary adds an authenticated no-body manual recalculation
operation. Owner, admin, and editor memberships are allowed; viewer, foreign,
missing, and archived accounts share a concealed 404 contract. The server
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

All values and intermediate aggregates use exact `NUMERIC(18,6)` Decimal
semantics. Native cash, portfolio, liability, and total breakdowns are
preserved only when complete; unavailable evidence remains distinct from an
empty exact breakdown. 5J-A performs no database selection, FX conversion,
persistence, authorization, or scheduling.

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
owns no transaction or write. NetWorthSnapshot physical projection begins in
5J-C.
