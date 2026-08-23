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

For Trading212 trades, executed settlement is canonical evidence. Buy principal
is fee-inclusive provider `Total` minus fee; sell principal is net provider
`Total` plus fee. The implicit direct trade rate is the exact ratio of quoted
asset notional (`quantity * source unit price`) to that principal. A standalone
provider exchange-rate field does not create currency-conversion movements.
Listing currency remains the quoted market currency, while movement and Holding
cost currency remain the settlement currency. Only the derived unit-cost and
weighted-average representations are rounded half-even at the `QUANTITY`
storage boundary; the principal and fee legs remain exact.

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

R6-A adds the already persisted AccountSnapshot `cashValueByCurrency` and
`netDepositsByCurrency` fields to this presentation contract. Each entry is an
immutable `(currency, amount)` value and public responses serialize the tuple
as a deterministic currency-sorted array rather than an unordered JSON object.
The decoder is the inverse of AccountSnapshot persistence: the physical value
must be a JSON object whose keys are exact uppercase three-letter ASCII
currencies and whose values are canonical six-decimal MONEY strings. Missing
fields, JSON numbers, alternative decimal spellings, overprecision, overflow,
NaN, and infinity fail closed. Empty objects are valid evidence only with a
zero scalar; negative cash and negative net deposits remain valid.

R6-A does not recalculate finance. A one-entry output-currency breakdown must
equal its scalar. Multi-currency evidence is checked for exact canonical
representation, but its scalar is not independently recomputed because the
physical snapshot audit retains full snapshot-time rates while historical net
deposit evidence retains only rate identities. Inventing another FX algorithm
would violate AccountSnapshot writer ownership. The reader therefore performs
no Transaction, Holding, price, or live-rate query and never falls back from a
missing breakdown to its scalar.

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

R6-A also aggregates cash and net-deposit breakdowns by exact original currency.
Entries from all accounts with the same currency are added with Decimal MONEY
arithmetic, currencies are unique and sorted ascending, and a currency present
in any input remains present even when its aggregate cancels to zero. No FX
conversion, latest-rate lookup, synthetic currency, or float is permitted.
The pre-existing scalar net-deposits value remains the exact sum of account
scalars; R6-A changes only the accompanying presentation evidence.

R6-B gives the two forms of evidence distinct presentation roles. The
`Hotovost` and `Čisté vklady` scalar cards are output-currency values.
`Hotovost podle měny` and `Čisté vklady podle měny` are original-currency
evidence whose rows retain the canonical server order and exact Decimal
strings. The UI does not imply that original-currency rows can be added without
FX or that their simple sum must equal the scalar.

Aggregate and selected-account views use their corresponding server summaries
by reference. Account switching is local and performs no fetch or financial
transformation. Empty breakdowns are explicit text states; negative amounts
and zero amounts remain visible. R6-B adds no sorting, merging, FX conversion,
scalar/breakdown reconstruction, legacy fallback, history override, backend
change, public-contract change, or schema change. The later R6 final audit
passed.
