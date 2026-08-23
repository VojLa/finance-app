# Modules

> Migration note: use the maintained split [!docs/domains/](../../domains/README.md)
> documents for module-specific work. This broad catalogue remains historical
> cross-domain reference; do not add new module rules here.

The Python code is organized under `backend/python/app/modules`. A module owns
its API adapter, service layer, and repository where those exist; routers stay
thin and shared database infrastructure lives outside modules.

| Module                  | Responsibility                                                                                         | Status                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `auth`                  | Verify a trusted HS256 session-bridge token and resolve its user                                       | Implemented                                                                 |
| `accounts`              | Account lifecycle, memberships, and invitations                                                        | Implemented                                                                 |
| `categories`            | Default/user category hierarchy and ownership                                                          | R11-E implemented                                                           |
| `budgets`               | Exact monthly plans, rollover, account scope, progress, and alerts                                     | R11-F implemented                                                           |
| `operational_dashboard` | Read-only persisted cash-flow, category, trend, and recent-transaction projection                      | R11-F implemented                                                           |
| `asset_aliases`         | Server-operator exact provider identity inventory and immutable onboarding                             | R5-B4 implemented; remediation re-audit passed                              |
| `liabilities`           | Canonical positive liability observations, atomic writes, and latest-as-of evidence                    | 5I-L1/L2A implemented; consumed by snapshots in 5I-L2B                      |
| `imports`               | Register/upload files; durable multi-file histories; RB reconciliation/reporting/liability/publication | R12 lifecycle and durable RB workflow implemented                           |
| `investments`           | Idempotent manual event commands, atomic Holding rebuild, and symbol-detail reads                      | R11-G implemented                                                           |
| `portfolio`             | Read accessible accounts and holdings, convert cost values using latest FX                             | Basic read endpoint implemented                                             |
| `portfolio_snapshot`    | Exact snapshot projection, currency breakdown reads, authorized APIs, and aggregation                  | R6-A/B contract and portfolio presentation implemented                      |
| `portfolio_history`     | Read-only exact NetWorthSnapshot history and deterministic public selection                            | R7-A Python API and R7-B browser/chart cutover implemented                  |
| `dashboard_snapshot`    | Pure dashboard projection and authorized exact API adapter                                             | 5L complete; final cross-boundary audit passed                              |
| transactions            | Exact cash transaction list and manual lifecycle with canonical revisions                              | R11-E implemented                                                           |
| ledger                  | Investment events and movements written by imports and manual investment commands                      | Canonical Python writers implemented                                        |
| holdings                | Project and rebuild holdings from active canonical investment history                                  | Pure projections, atomic writer, and authorized manual endpoint implemented |
| net_worth               | Exact aggregation, persistence, and authenticated manual recalculation                                 | 5J-A–5J-E implemented                                                       |
| snapshot_refresh        | Cross-domain planning, persisted coverage, coordinated execution, and manual API                       | R5-B3A coordinator used by R5-B3B manual and R5-B3C import paths            |
| snapshots               | Exact account valuation, persistence, and authorized manual recalculation                              | 5I complete; output-currency chain implemented through 5K-C5                |
| market_data             | Exact market requirements, provider ports, orchestration, and atomic evidence writes                   | R5-A through R5-B3C coordinated production consumption implemented          |
| prices / FX             | Canonical price and direct-FX observation models, validation, and providers                            | Twelve Data direct FX plus CoinGecko and Twelve Data prices                 |
| dashboard / reporting   | Dashboard read models                                                                                  | Snapshot read path complete and final-audited through 5L                    |

`app/db/models` is a complete physical-schema mirror, grouped by domain. It is
not a service layer and it intentionally defines no ORM relationships, so
repository queries remain explicit and cannot trigger hidden asynchronous lazy
loads.

The R5-A `market_data` module composes five explicit boundaries over the
unchanged `PriceSnapshot`, `ExchangeRate`, Asset, Listing, Alias, Holding, and
canonical history schema. A read-only requirements repository and planner run
inside a caller-owned `REPEATABLE READ, READ ONLY` transaction. The immutable
plan contains exact Listing/provider identities and direct FX pairs, including
historical requirements through each persisted event timestamp. It performs no
provider call, lock, write, clock access, symbol guessing, first-alias fallback,
inverse-rate derivation, or cross-rate derivation.

Price and FX providers are injected protocols registered by exact source enum.
The registry permits at most one adapter per non-manual source and performs no
fallback between sources. Independent provider acquisitions run outside every
database transaction in a bounded `TaskGroup` (maximum four concurrent
operations). Results retain the immutable plan order; one acquisition failure
cancels and awaits its siblings, and no write starts. Only after all
observations validate does the single append-only `SERIALIZABLE` writer commit
the whole price/FX batch atomically. Production composition registers exactly
`ExchangeRateSource.twelve_data` for direct `FROM/TO` FX evidence, plus
`PriceSource.coingecko` for crypto and `PriceSource.twelve_data` for listed
securities. Historical CNB/Yahoo source identities remain readable but cannot
be selected by production composition.

`local_free` is an environment-gated, non-production fixture policy, not a
production fallback. It maps crypto prices to CoinGecko, non-crypto listed
prices to Yahoo Finance, and every FX requirement to Yahoo Finance's requested
direct pair. It does not invert, pivot, triangulate, cross-rate, or fall back
between providers. The canonical production policy remains unchanged: CoinGecko
for crypto, Twelve Data for non-crypto prices, and Twelve Data for direct FX.

R5-B4 adds the `asset_aliases` application module and
`scripts/asset_alias.py` as the supported server-operator boundary for those
exact persisted identities. It deliberately has no FastAPI or browser
surface. A read-only, deterministic unresolved inventory lists only
provider-compatible Assets referenced by nonzero Holdings and missing the
selected alias. Existing Listing symbols, providers, exchanges, and
currencies are context for a human operator only: the inventory performs no
identity recommendation, provider lookup, network request, or inference.

The onboarding command requires the Asset ID plus exact expected symbol,
Asset type, currency, and optional ISIN before it accepts a provider identity.
CoinGecko is limited to crypto and one canonical CoinGecko ID. Twelve Data is
limited to stock, ETF, bond, commodity, and other Assets and reuses the
canonical quote identity parser for byte-exact
`{"symbol":"AAPL","mic_code":"XNAS"}`. Cash is unsupported, and there is no
provider fallback.

The create-only writer owns one `SERIALIZABLE` transaction. It takes advisory
locks for `(asset_id, provider)` and `(provider, external_id)` in canonical
sorted order, then validates existing state and physically reloads a new row.
New alias IDs use UUIDv5 namespace
`b1d66d76-35f0-4db0-b1d9-0f5452d4a27c` with identity payload
`asset_id + NUL + provider.value`. Exact state replays without updating even
`createdAt`; any repoint, replacement, duplicate, corrupt state, or
deterministic ID collision fails closed. Only SQLSTATE `40001`, `40P01`, or
`23505` retries, for at most three complete attempts.

Durable Anycoin finalization has one imports-owned, closed allowlist above that
same writer: an exact persisted Anycoin asset movement with normalized symbol
`BTC`, `AssetType.crypto`, and its canonical exchange Listing may receive
`AssetAlias(provider=coingecko, externalId=bitcoin)`. Canonical posting/replay
must finish first; alias creation/replay finishes before Holdings and market
acquisition. The boundary rejects zero or multiple canonical BTC identities,
wrong Asset/Listing state, and immutable alias conflicts before provider HTTP.
It contains no ETH or generic symbol map, provider discovery, Yahoo/pivot
fallback, public API, second writer, or direct `AssetAlias` construction.

Imports also owns one explicit display-only rule for this exact source tuple:
Anycoin crypto `BTC` has canonical `Asset.name=Bitcoin`. Normalization supplies
it for new rows and resolver replay enriches only a legacy NULL name while the
same provider lock and Asset row lock are held. A conflicting non-NULL name
fails closed; non-BTC symbols are never named by ticker guessing. This rule does
not derive or replace the independent CoinGecko alias identity.

R5-B2B0 adds `AssetAliasProvider.twelve_data` and
`PriceSource.twelve_data` across PostgreSQL and SQLAlchemy. R5-B2B1 narrows that
opaque value to byte-exact canonical
JSON `{"symbol":"AAPL","mic_code":"XNAS"}` and registers the production
provider. The planner still projects only persisted identity; it never derives
symbol or MIC from Trading212, Listing, Asset, ISIN, name, exchange, or country.

Stooq was rejected for this boundary because the reviewed public surface did
not establish the authoritative API and quote-time timezone contract required
by fail-closed evidence timestamps. Twelve Data was selected for R5-B2B1
because its official `/quote` documentation provides exact MIC filtering,
intraday UTC output, interval timestamps, and `last_quote_at`.

The Twelve Data adapter makes one bounded HTTPS `/quote` request per exact
requirement with `interval=1min`, `timezone=UTC`, JSON output, regular-session
prices, and ten requested decimal places. Its API key is an optional
server-side secret sent only in the recommended Authorization header;
production requires it, while a missing development/test key fails before
HTTP. The short-lived transport follows no redirects and has no retry, cache,
cookie, discovery, batch request, or alternate endpoint.

The strict JSON parser requires exact response symbol, MIC, Listing currency,
UTC datetime, interval timestamp, `last_quote_at`, and a positive string
`close`. For this one-minute contract the two timestamps must be identical and
minute-aligned, and the UTC datetime must represent that exact epoch.
`last_quote_at` becomes the naive UTC observation time. Duplicate keys, error
objects, excessive structure, non-string price, timestamp mismatch, stale or
future evidence, and `NUMERIC(28,10)` overprecision fail without repair.

The Twelve Data FX adapter performs one HTTPS `/time_series` GET per exact
direct pair. It requests daily UTC data from seven days before `through` through
the following day and selects the newest point no later than `through`. It has
no retry, response cache, inverse derivation, pivot, cross-rate derivation, or
alternate provider. Timeout, streamed response-byte limit, User-Agent,
credential-free HTTPS URL, and redirect rejection are explicit configuration.
The API key is required before HTTP and travels only in the Authorization
header, never in the logged request URL.

The strict JSON parser validates status, exact `FROM/TO` symbol, unique
`YYYY-MM-DD` rows, and a positive Decimal `close` already representable as
`NUMERIC(18,8)`. Midnight on the provider date is the effective timestamp. An
older weekend or holiday point is accepted only through the shared seven-day
freshness check; future, stale, quota, schema, and direction failures close the
entire evidence refresh.

Canonical observations use exact `Decimal`, direct currency direction, and
naive UTC `TIMESTAMP(3)` values. Prices must fit `NUMERIC(28,10)` and direct FX
must fit `NUMERIC(18,8)` without rounding repair. The shared freshness policy
accepts price age through 72 hours and FX age through seven calendar days,
including the exact boundary. Future or older evidence is unavailable. The
unchanged snapshot selector now applies the same limits to current prices,
snapshot-time FX, and historical event-date FX. Same-currency values bypass FX
structurally and never synthesize a rate of one.

Only after all provider observations validate does the append-only market
writer start one bounded `SERIALIZABLE` attempt. It acquires all price and FX
advisory locks in canonical order, row-locks existing identities, creates
deterministic UUIDv5 rows or exactly replays them, and verifies every physical
column after flush/reload. A different existing value conflicts without
update or repair; any provider, state, or persistence failure leaves no partial
price/FX batch.

The R5-B2A CoinGecko adapter calls only the configured HTTPS `/simple/price`
endpoint, once per exact requirement, with the persisted alias ID and
lower-case Listing quote currency. It performs no ticker or name lookup,
`/coins/list` discovery, hard-coded BTC mapping, retry, redirect, or cache. Its
optional Demo key is an HTTP-header-only secret. Strict JSON parsing retains
the exact `Decimal` and provider `last_updated_at` timestamp; duplicate keys,
excess identities, invalid numbers, future/stale time, or `NUMERIC(28,10)`
overprecision fail without rounding or timestamp repair. The exact Anycoin BTC
durable-import allowlist onboards `bitcoin` before acquisition; another Anycoin
Listing without a CoinGecko alias is therefore unavailable. Trading212-style listed
securities require their separate canonical Twelve Data alias; the adapter
does not reuse the broker identity. R5-B3A composes the internal refresh and
R5-B3B connects it to the approved manual endpoint and R5-B3C connects it to
approved import post-processing. The post-B4 remediation re-audit passed and
R5 is implemented.

R5-B3A adds one internal orchestrator in `snapshot_refresh` without moving
financial logic out of `market_data`, `snapshots`, or `net_worth`. Its
immutable command is validated before I/O. It first projects the exact user,
snapshot timestamp, and caller-supplied `created_at` into the production
market-evidence service. Only a validated successful market result permits the
existing `UserSnapshotRefreshExecutor` to receive every original snapshot
field unchanged.

The shared session must be idle at entry and after both dependencies. Market
planning completes its read transaction before provider HTTP, provider HTTP
runs outside every transaction, and the market writer commits before snapshot
execution. A dependency transaction leak is rolled back and surfaced as an
internal runtime error before another stage can start.

This is deliberately two-phase persistence, not one atomic transaction.
Market failure prevents the snapshot call. Snapshot failure after market
success does not delete or compensate append-only `PriceSnapshot` or
`ExchangeRate` evidence. A zero-price, zero-FX market plan is valid and still
runs the snapshot executor. The combined immutable result cross-validates
user, timestamp, output currency, canonical market IDs, create/replay counts,
snapshot dispositions, aggregate counts, and exact AccountSnapshot lineage.

R5-B3B wires the existing authenticated manual endpoint to that orchestrator
with the same request-scoped session and application-state settings. After the
authentication read transaction closes, one clock read creates the canonical
minute bucket and one exact market-backed command. The route and successful
response remain unchanged; market requirements, IDs, provider identities, and
counts are not public.

There is no direct manual executor fallback. Market failure prevents snapshot
execution, while snapshot failure after the market commit preserves valid
append-only evidence. Empty market plans continue normally. Production
mixed-currency endpoint refresh uses exact Twelve Data and CoinGecko prices plus
exact direct Twelve Data FX. Non-CZK outputs request their direct pairs (for
example USD/EUR); missing pairs fail through the generic unavailable contract
without CNB, Yahoo, ECB, inverse, pivot, or manual fallback.

R5-B3B adds no new endpoint, scheduler, worker, queue, retry, cache, frontend,
schema, migration, or OpenAPI surface. R5-B3C now makes the existing import
post-processing boundary call the same market-backed service after posting and
Holding rebuild. The R5 final audit completed with verdict NOT READY, R5-B4
implements the identified alias-onboarding remediation, and the independent
remediation re-audit passed. Overall R5 is implemented.
