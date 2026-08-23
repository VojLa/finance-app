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

## Exact provider alias onboarding

R5-B4 makes `AssetAlias` an explicitly onboarded, server-owned global catalog
identity. It does not make aliases user/account data and adds no public
mutation endpoint. The read-only unresolved inventory returns only compatible
Assets referenced by nonzero Holdings and missing the selected provider
alias. Listing symbols, provider symbols, exchanges, and currencies appear as
operator context but can never supply or derive `externalId`.

The writable alias providers are `coingecko`, `twelve_data`, and
`yahoo_finance`. CoinGecko
requires `Asset.assetType=crypto` and one exact ASCII CoinGecko ID with no
whitespace repair, control characters, URL/list delimiters, or multi-ID list.
Twelve Data permits only stock, ETF, bond, commodity, and other Assets; cash
and crypto are rejected. Its `externalId` must already equal the canonical
parser output, for example `{"symbol":"AAPL","mic_code":"XNAS"}`. Generic
inventory, provider, planner, and operator paths perform no ticker, name, ISIN,
broker-symbol, Listing-MIC, exchange, first-alias, or network discovery.
Yahoo Finance aliases are operator-owned non-crypto identities used only by
the explicit non-production `local_free` source policy; for example the
Trading212 `VUAA.IT` Listing is mapped explicitly to `VUAA.MI`, never by a
suffix or exchange inference rule. Production does not register Yahoo for new
market evidence.

The only source-owned automatic exception is the exact durable-import allowlist
`(anycoin, crypto, BTC) -> (coingecko, bitcoin)`. It runs after canonical
`Asset`/`AssetListing` posting (including posting replay) and before Holdings or
market acquisition. It reloads only asset movements belonging to the exact
account and batch set, requires the canonical Anycoin exchange Listing and a
single canonical BTC Asset, and then delegates to the unchanged create-only
`AssetAliasWriter`. ETH, WBTC, case repair, arbitrary symbols, provider lookup,
Yahoo, pivoting, and public mutation remain unsupported. A missing or mismatched
BTC Asset/Listing, multiple canonical BTC Assets, or an existing conflicting
`coingecko/bitcoin` owner fails before market acquisition without repointing an
alias.

Anycoin's separate display identity is equally closed:
`(anycoin, crypto, BTC) -> Asset.name Bitcoin`. New normalized BTC rows carry
that value. Resolver replay may enrich only an exact existing Anycoin BTC Asset
whose name is NULL, under the existing provider advisory and row locks. An
existing `Bitcoin` value replays; any other non-NULL name fails without rename
or repoint. Other Anycoin symbols receive no derived display name.

Before persistence the immutable command reloads the exact Asset and verifies
the caller-supplied expected symbol, type, currency, and optional ISIN. Its
naive UTC `createdAt` must already fit `TIMESTAMP(3)`; the application service
does not read a clock or repair a timestamp. The server CLI reads its clock
once and passes the value into the command.

An alias is immutable under two identities: `(asset_id, provider)` and
`(provider, external_id)`. The writer locks both scopes canonically inside one
writer-owned `SERIALIZABLE` transaction. A new row uses UUIDv5 namespace
`b1d66d76-35f0-4db0-b1d9-0f5452d4a27c` and payload
`asset_id + NUL + provider.value`. That namespace is a public identity
contract. Exact existing physical state, including a valid historical
non-deterministic ID, replays without updating `createdAt`. A different alias
for the same Asset/provider, an external identity owned by another Asset,
multiple aliases, corrupt state, or deterministic-ID collision fails without
update, delete, move, or replacement.

After insert the writer flushes, reloads, and verifies exact ID, Asset,
provider, external identity, and creation timestamp. At most three full
transaction attempts are allowed, and only for serialization failure
`40001`, deadlock `40P01`, or unique race `23505`. Validation, target mismatch,
unsupported provider/type, corruption, and immutable conflicts never retry.
Dry-run and unresolved inventory execute read-only and never enter the writer.

FX requirements always describe one direct
`from_currency -> output_currency` pair. Current requirements cover account,
cash, Listing-price, Holding cost-basis, and liability currencies at the
snapshot timestamp. Historical requirements use the timestamp of the
persisted Transaction, InvestmentEvent, or related canonical movement amount.
They never substitute snapshot-time FX for event-date FX. Same currency is a
structural bypass, not an `ExchangeRate` row; inverse and cross rates are not
derived in R5-A.

A nonzero investment Holding always keeps its exact Listing-price requirement.
Its average-buy-price and ordered cost-basis map are one evidence pair: both may
be NULL only when the canonical source cannot prove purchase cost. That unknown
basis contributes no cost-currency FX requirement, because there is no cost
amount to convert; price and Listing/account-currency requirements remain.
One-sided, empty, zero, non-finite, or malformed cost state still fails closed.

The explicit 0.1 freshness policy is 72 hours for prices and seven calendar
days for FX. Evidence exactly at the maximum age is valid; future or older
evidence fails closed. Snapshot evidence selection applies this same policy to
current price, current FX, and historical event-date FX. Missing or stale
evidence therefore creates neither a partial AccountSnapshot nor a partial
NetWorthSnapshot.

R11-J replaces the historical CNB runtime with exactly one production FX
adapter: Twelve Data `/time_series`. Every requirement is the requested direct
`FROM/TO` pair, including foreign-to-foreign pairs such as `EUR/USD`. The
adapter never inverts a response, triangulates through CZK, substitutes another
provider, or persists a synthetic pair. It requests a bounded daily window and
selects the newest non-future point through the explicit requirement timestamp;
weekend and holiday evidence must still satisfy the shared seven-day policy.

The strict JSON parser requires an exact response symbol, unique daily dates,
positive finite Decimal `close` strings, and the `NUMERIC(18,8)` boundary. The
API key is sent only in the Authorization header, so request logging cannot
expose it in a URL. HTTP, quota, schema, direction, freshness, and precision
failures are closed without rounding, retry, inversion, or fallback.

Market evidence persistence is append-only. Price UUIDv5 identity is based on
Listing, observation timestamp, and source; FX UUIDv5 identity is based on the
direct pair, effective timestamp, and source. Price, rate, creation time, User,
Account, and randomness are excluded from those identities. Exact persisted
state replays without a write. A different value under the same identity is a
conflict, and the single mixed price/FX batch rolls back completely. R5-A
defines provider ports. R11-J PostgreSQL tests use mocked Twelve Data HTTP
responses with the real production registry, service, and writer. Exact replay
uses the same deterministic identities without duplicate rows.

R5-B2A adds exactly one production price source, CoinGecko, without changing
the physical model. A requirement is eligible only through one persisted exact
`AssetAlias(provider=coingecko, externalId=<CoinGecko ID>)`; Listing tickers,
Asset names, `/coins/list`, and hard-coded symbol mappings are not identities.
The provider's positive exact Decimal and actual `last_updated_at` UTC time are
validated by R5-A and persisted append-only as `PriceSnapshot`. The timestamp
is not clamped, and overprecision is not rounded. Durable Anycoin BTC
finalization first creates or replays its one allowlisted exact alias through
the approved writer; every other Anycoin crypto asset without an explicit alias
fails before HTTP. Trading212 listed securities use only an exact persisted
Twelve Data alias.
PostgreSQL tests use mocked HTTP but the production factory, planner, writer,
snapshot executor, and exact portfolio/dashboard readers. Public
market-evidence orchestration remains assigned to R5-B3, so overall R5 remains
in progress.

R5-B2B0 extends the two existing provider-identity enums with the exact value
`twelve_data`. An `AssetAlias(provider=twelve_data, externalId=...)` stores one
provider-owned identity; the planner never derives it from a
Trading212 symbol, Asset symbol, ISIN, name, exchange, MIC, or another alias.
When a matching provider is injected, that unchanged string becomes the
requirement's provider symbol. R5-B2B1 defines its byte-exact canonical form as
`{"symbol":"AAPL","mic_code":"XNAS"}` and production composition now registers
Twelve Data alongside CoinGecko.

The Stooq candidate was rejected because the reviewed public surface did not
establish an authoritative API and quote-time timezone contract. Twelve
Data's official `/quote` contract documents MIC filtering, an intraday UTC
timezone, the interval timestamp, and `last_quote_at`. The provider requests
one exact quote with `interval=1min` and `timezone=UTC`; its API key exists only
in the server-side Authorization header.

The response `close` string becomes the exact positive Decimal price.
`last_quote_at` becomes the evidence timestamp only when it equals the
minute-aligned interval `timestamp` and the UTC response `datetime` represents
the same instant. Identity, currency, timestamp, freshness, and physical
precision mismatches fail closed without rounding, clamping, or fallback.
Production composition is CoinGecko plus Twelve Data for prices and Twelve Data
for direct FX. The explicit non-production `local_free` policy instead maps
crypto to CoinGecko, non-crypto assets to exact Yahoo aliases, and direct FX to
Yahoo; it rejects fallback, inverse, and pivot acquisition. Persisted `cnb` and
inactive-provider rows remain readable audit evidence but are not eligible for
selection under the active immutable source policy.

The fixed UUIDv5 namespaces are
`8c46da0b-b09a-49c7-94f1-a510cf4c2f7c` for `PriceSnapshot` and
`93484f65-330c-47e9-a592-49e4fd9a5122` for `ExchangeRate`. Changing either
value is an identity-contract change, not an implementation detail.

## Market-backed snapshot refresh

R5-B3A defines one immutable internal command that carries the exact user,
snapshot bucket, granularity, source, calculation version, calculation and
creation timestamps, and recalculation flag. All timestamps must already be
naive UTC values exactly representable as `TIMESTAMP(3)`; the service neither
rounds them nor substitutes a clock value. The command is validated completely
before market persistence so invalid snapshot metadata cannot create market
evidence and then fail only at the second phase.

Execution order is fixed: the production `MarketEvidenceRefreshService` runs
first, its result is validated, and only then may
`UserSnapshotRefreshExecutor` run. Both projections retain the original user
and snapshot timestamp. Market refresh receives the original `created_at`;
snapshot refresh receives every command field unchanged. An empty market plan
with zero price and FX requirements is complete valid evidence, not an
unavailable state, and therefore continues to snapshot execution.

Market evidence and the snapshot graph are two separate committed phases.
There is no outer atomic transaction. Market failure creates no partial
price/FX batch and prevents every AccountSnapshot or NetWorthSnapshot call.
After a successful append-only market commit, later snapshot failure leaves
the valid PriceSnapshot and ExchangeRate rows intact. The orchestrator never
deletes, compensates, repairs, or attempts to roll back already committed
market evidence.

The shared session is idle at each stage boundary. The market planner's
read-only transaction closes before provider HTTP, provider I/O occurs outside
database transactions, the market writer transaction closes before snapshot
execution, and the snapshot executor must also return an idle session. A
dependency that leaks a transaction is rolled back and produces an internal
runtime failure before the next stage.

The immutable combined result cross-validates exact user, timestamp, and
output currency ownership. Market counts are nonnegative, canonical ID tuples
are sorted and duplicate-free, and create plus replay counts equal persisted
identity counts. Snapshot executions must have valid mode/disposition counts,
and their canonical `(account_id, snapshot_id)` sequence must exactly equal
the guarded NetWorth dependency lineage. Malformed dependency results fail
closed rather than crossing the boundary.

R5-B3B now uses this command and combined result at the unchanged authenticated
manual endpoint. The request-scoped settings and database session compose the
production service; authentication closes its read transaction before one
server clock read derives the manual minute bucket. Market evidence refresh
always precedes snapshot execution, and no direct executor fallback remains.

The public manual response still contains only the validated snapshot manifest
and summary. It exposes no market IDs, provider identities, requirements, or
counts. A market failure prevents the snapshot graph. Snapshot failure after a
successful market commit does not delete or compensate evidence because the
two stages are intentionally separate committed phases. An empty market plan
is valid and continues to snapshot execution.

CZK-output users may combine USD and EUR holdings through exact Twelve Data,
CoinGecko, and ČNB evidence. A non-CZK output remains valid when no cross-FX is
needed; unsupported direct FX such as USD-to-EUR is generically unavailable
without ECB, inverse, cross-rate, or manual fallback. R5-B3B changes no
endpoint, frontend, schema, migration, or OpenAPI contract. R5-B3C now uses
this service from import post-processing after canonical posting and Holding
rebuild. The R5 final audit completed with verdict NOT READY, R5-B4 implements
the identified alias-onboarding remediation, and the independent remediation
re-audit passed. R5 is implemented.
