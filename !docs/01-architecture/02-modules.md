# Modules

The Python code is organized under `backend/python/app/modules`. A module owns
its API adapter, service layer, and repository where those exist; routers stay
thin and shared database infrastructure lives outside modules.

| Module                | Responsibility                                                                       | Status                                                                      |
| --------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `auth`                | Verify a trusted HS256 session-bridge token and resolve its user                     | Implemented                                                                 |
| `accounts`            | Account lifecycle, memberships, and invitations                                      | Implemented                                                                 |
| `liabilities`         | Canonical positive liability observations, atomic writes, and latest-as-of evidence  | 5I-L1/L2A implemented; consumed by snapshots in 5I-L2B                      |
| `imports`             | Register, upload, parse, normalize, and deduplicate CSV import batches               | Implemented through duplicate detection                                     |
| `portfolio`           | Read accessible accounts and holdings, convert cost values using latest FX           | Basic read endpoint implemented                                             |
| `portfolio_snapshot`  | Exact snapshot projection, reads, authorized APIs, and pure aggregation              | 5L complete; final cross-boundary audit passed                              |
| `dashboard_snapshot`  | Pure dashboard projection and authorized exact API adapter                           | 5L complete; final cross-boundary audit passed                              |
| transactions          | Cash transaction lifecycle and classification                                        | Database schema only                                                        |
| ledger                | Investment events and movements                                                      | Database schema only                                                        |
| holdings              | Project and rebuild holdings from active canonical investment history                | Pure projections, atomic writer, and authorized manual endpoint implemented |
| net_worth             | Exact aggregation, persistence, and authenticated manual recalculation               | 5J-A–5J-E implemented                                                       |
| snapshot_refresh      | Cross-domain planning, persisted coverage, coordinated execution, and manual API     | 5K complete; 5M-A exact read manifest implemented                           |
| snapshots             | Exact account valuation, persistence, and authorized manual recalculation            | 5I complete; output-currency chain implemented through 5K-C5                |
| market_data           | Exact market requirements, provider ports, orchestration, and atomic evidence writes | 0.1-R5-A provider-independent foundation implemented                        |
| prices / FX           | Canonical price and direct-FX observation models and pure validation                 | R5-A contracts implemented; concrete production providers remain deferred   |
| dashboard / reporting | Dashboard read models                                                                | Snapshot read path complete and final-audited through 5L                    |

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
fallback between sources. Provider calls occur sequentially and outside every
database transaction. The R5-A production default registry is empty and
therefore fails safely; deterministic fake providers exist only in tests.
Concrete Yahoo, CoinGecko, ECB, CNB, or other internet adapters are not part of
R5-A.

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
price/FX batch. R5-B will supply concrete production adapters and compose this
foundation with approved import/manual workflows. Overall R5 remains in
progress.

The Python `portfolio_snapshot` module owns the pure 5L-A single-account
presentation contract. It accepts only immutable, already validated
AccountSnapshot and item evidence, validates exact physical scales, output/native
currency separation, aggregate and allocation invariants, supported account
shapes, metadata, uniqueness, and canonical ordering, and returns frozen view
dataclasses. Canonical position ordering is
`(asset_type, symbol, listing_id, item_id)`. The module performs no database,
ORM, authorization, price or FX selection, clock access, ID generation, or
serialization and does not change the existing portfolio API. A persisted exact
reader is implemented separately in 5L-B, and 5L-C exposes its pure result
through an authorized account-specific endpoint.

The implemented 5L-B reader selects one exact AccountSnapshot by account,
timestamp, granularity, and output currency inside a caller-owned coherent
transaction. It loads AccountSnapshotItems and their AssetListing/Asset
metadata with explicit read-only joins, validates the complete immutable graph,
maps database enums and physical currency semantics into the pure 5L-A source,
and invokes the pure projection once. It never selects a latest snapshot or
reads Holdings, prices, exchange rates, users, memberships, or live balances.
The repository owns no transaction, write, or lock. The 5L-C application
service closes the authentication read transaction and then places
authorization and the exact reader in one fresh `REPEATABLE READ` transaction,
with the isolation statement preceding every authorization query. It permits
explicit owner/admin/editor/viewer memberships and hides foreign, missing, and
archived accounts behind the same not-found contract.

The thin `GET /api/v1/portfolio/accounts/{account_id}/snapshot` adapter accepts
only exact identity selectors. Its response serializes Decimal values as JSON
strings and excludes membership/User data, internal selected-row lineage,
persistence timestamps, and JSONB audits. It performs no financial
recalculation and reads no Holding, PriceSnapshot, ExchangeRate, price, or FX
evidence. The legacy portfolio reader remains registered and unchanged;
the authorized single-account endpoint remains unchanged.

The pure 5L-D boundary aggregates only complete 5L-A views. It requires one
shared timestamp, granularity, output currency, and calculation version plus
unique account and snapshot identities. Accounts are canonically ordered while
positions remain account-scoped in their existing 5L-A order, including when
the same asset or listing occurs in multiple accounts. Summary fields use exact
high-precision Decimal sums and must remain representable as MONEY; aggregate
overflow and formula mismatch fail closed.

5L-D has no database, ORM, reader, authorization, transaction, API, price, FX,
Holding, clock, or I/O boundary. It adds no endpoint and does not duplicate
single-account or position financial validation.

The pure `dashboard_snapshot` module implements 5L-E over one complete
`MultiAccountPortfolioView`. It maps the exact summary, builds deterministic
account cards, groups investment positions by asset type, and ranks every
account-scoped position. Dashboard allocations use the aggregate investment
value as their denominator; they never reuse account-local allocation.
Liabilities remain summary values rather than positions, so zero-investment
and liability-only dashboards have no investment breakdown.

5L-E performs only exact Decimal structural arithmetic, including
`assets = cash + investment`, and validates MONEY and PERCENTAGE
representability without rounding repair. It accesses no database, ORM,
authorization, reader, Holding, price, FX, clock, or historical input and adds
no endpoint. Public portfolio/dashboard orchestration is owned by 5L-F;
historical dashboard series are outside this snapshot projection.

The 5L-F public read boundary exposes only
`POST /api/v1/portfolio/snapshot` and `POST /api/v1/dashboard/snapshot`.
Both require the complete exact common snapshot metadata plus an explicit
non-empty account selector tuple; optional snapshot IDs are lineage guards.
POST carries this structured selector body but remains read-only. Accounts are
never discovered from membership and no time, currency, latest row, or fallback
is inferred.

After closing the authentication dependency transaction, the portfolio service
starts one `REPEATABLE READ` transaction with isolation setup as its first SQL
statement. Canonically ordered account authorization and exact 5L-B reads run
sequentially in that same transaction through the shared authorized account
reader. Every selector must succeed, and no partial response exists. 5L-D is
called once for aggregation; the dashboard service then calls 5L-E once after
the immutable read completes and does not access the database itself.

Public portfolio output retains account-local position allocation and detailed
5L-A position fields. Dashboard output exposes only the 5L-E summary, account
cards, asset-type allocations, and global position ranking. Every Decimal is a
JSON string. Foreign, missing, and archived accounts remain indistinguishable,
and persisted evidence failures use one generic unavailable response. The
legacy portfolio route and exact single-account 5L-C route are unchanged;
historical series remain outside 5L-F.

The final 5L audit changes no production module. Static dependency tests,
cross-projection tests, endpoint/OpenAPI tests, and PostgreSQL event
instrumentation now permanently guard the complete persisted-reader,
authorization, transaction, aggregation, dashboard, and serialization path.
They prove one isolation-first `REPEATABLE READ` financial transaction per
request, read-only and lock-free SQL, exact single/multi/dashboard consistency,
deterministic responses, access non-disclosure, and the absence of public
membership or internal lineage evidence. Concurrent portfolio and dashboard
tests prove coherent database perspectives rather than mixed account state.

The internal holdings rebuild service is caller-transaction-owned. It
serializes one account with a dedicated transaction advisory lock, then acquires
all existing 5G account/source posting locks before locking active events,
movements, current Holdings, and their explicit Asset/Listing evidence.
Identical history is a read-only replay; changes use a deterministic UUIDv5
Holding identity and one caller-supplied `TIMESTAMP(3)` value.

The thin public `POST /api/v1/accounts/{account_id}/holdings/rebuild` adapter
delegates to an application service. That service locks the authenticated
principal's persisted membership, permits owner/admin/editor, supplies one
request timestamp, validates the public response, and owns the commit/rollback
boundary around the unchanged internal writer. Exact projection failures map
to one generic conflict response. No rebuild is triggered automatically by
import posting, and no ImportLog is written.

The Python `snapshots` module owns the pure 5I-A valuation contract, the
read-only, caller-transaction-owned 5I-B persisted-evidence adapter, the pure
5I-C physical projection, and the atomic internal 5I-D writer. The adapter
selects latest unambiguous persisted prices and direct FX, derives active
account-type-specific balances, and derives lifetime financial metrics only
where persisted classifications prove completeness, then delegates valuation
arithmetic to 5I-A. Cash-account net deposits, realized investment P/L, fees,
and taxes are tagged unsupported rather than silently zeroed because persisted
evidence does not prove them complete. Cash-account unrealized P/L is
structurally zero because Holdings are forbidden. It writes no snapshot rows
and owns no transaction. 5I-C rejects every unsupported physical metric,
generates deterministic snapshot/item UUIDv5 identities, serializes exact
fixed-scale JSONB evidence, and maps every ORM column without constructing ORM
entities. The writer owns one outer transaction, uses an identity advisory
lock, reuses sorted import account/source locks, row-locks canonical and Holding
evidence, and takes compatible PriceSnapshot/ExchangeRate `SHARE` locks before
selecting evidence. Its optional output currency resolves to persisted Account
currency when omitted and otherwise scopes the physical advisory identity,
evidence request, projection verification, and replay lookup. It inserts one
complete graph or performs an exact read-only replay; persisted differences
fail without repair. The public snapshot adapter exposes only
`POST /api/v1/accounts/{account_id}/snapshots/recalculate`. A thin router
accepts an optional body containing only an exact canonical `outputCurrency`
and delegates to an application service that permits persisted
owner/admin/editor memberships, hides viewer/foreign/missing/archived accounts,
closes the authentication lookup transaction, and calls the atomic writer once
on an idle session. Missing or null currency preserves Account-currency
behavior; another explicit currency selects a separate physical identity.
Server-owned minute-bucket metadata makes repeated calls within one minute
exact replays. Evidence/state failures and physical conflicts use generic 409
responses without exposing financial or FX evidence.

For credit-card, loan, and mortgage accounts, the snapshot writer stabilizes
canonical observations with a `LiabilityBalance` table `SHARE` lock and
composes the liability selector exactly once. Same-currency writes bypass
Holdings, prices, FX, Transactions, and investment history; mixed-currency
writes additionally stabilize the PriceSnapshot/ExchangeRate tables before
selecting their direct FX evidence. The positive selected balance is stored
in scalar `liabilitiesValue`, `totalValue` is its exact negative, and there are
no items. The schema has no liability-breakdown column; this is sufficient for
the enforced single-currency contract because liability and Account currencies
must match. Same-minute exact state replays, while changed evidence conflicts
without overwrite. Bank, cash, and savings remain non-persistable.

The `liabilities` module exposes a caller-transaction-owned, read-only
latest-as-of selector and an internal transaction-owning append writer over
canonical `LiabilityBalance` observations. Both validate supported account
type, account currency, exact MONEY components, the total formula, and
timestamp precision. The writer locks the Account, then sorted
timestamp/source and optional external-identity transaction advisory scopes,
and inserts one deterministic UUIDv5 row or validates an exact read-only
replay. Conflicts are never updated or repaired; any failure rolls back the
single writer-owned transaction. Neither boundary derives debt from ordinary
Transactions or falls back to zero. No public liability-observation endpoint
exists.

Authorization is established at request time under the current application
contract; the Account itself is revalidated by the writer under lock, while a
membership revocation between authorization and writer commit remains a
documented narrow race. Canonical liability evidence selection exists in
5I-L1, the internal atomic observation writer in 5I-L2A, and authorized manual
snapshot consumption in 5I-L2B. Public liability ingestion remains deferred.
`NetWorthSnapshot` remains outside Step 5I.

The Python `net_worth` module contains the pure 5J-A projection plus the
caller-transaction-owned 5J-B persisted-evidence adapter. The adapter discovers
the User's full current membership/account set, excludes consistently archived
accounts, fails if any active account type is not physically snapshot-capable,
and batch-selects one exact timestamp/granularity/currency/version
AccountSnapshot per eligible account. It strictly parses physical JSONB
breakdowns and delegates all aggregation to 5J-A exactly once.

Native breakdown precision is category-specific: cash and liability use
MONEY (`NUMERIC(18,6)`), portfolio uses QUANTITY (`NUMERIC(28,10)`), and total
native net worth also uses QUANTITY because it combines the other three
categories. Scalar net-worth values remain MONEY. The adapter and projection
never round or truncate scale-10 portfolio evidence.

The multi-query adapter requires an already active `REPEATABLE READ` or
`SERIALIZABLE` transaction and verifies that boundary before reading. It owns
no begin, commit, rollback, savepoint, flush, or write. This prevents a
concurrently committed Account or AccountSnapshot from producing a mixed view.
The physical AccountSnapshot has no liability-breakdown field, so unavailable
liability native evidence remains `None`.

The pure 5J-C persistence projection maps complete 5J-B evidence into all and
only physical `NetWorthSnapshotModel` fields. It uses deterministic UUIDv5
identity over `(userId, timestamp, currency, granularity)`, explicit
caller-supplied persistence timestamps/source, scalar MONEY values, and
category-specific fixed-scale native JSON strings. SQL NULL and exact empty
JSON remain distinct, `exchangeRates` stays NULL because 5J performs no FX,
and selected AccountSnapshot lineage remains an immutable non-persisted audit
because the schema has no lineage columns. The projection constructs no ORM
object and performs no I/O. Database writes, replay/conflict handling,
authorization, HTTP, FX conversion, and scheduling remain unimplemented.

Before JSON serialization, 5J-C independently rederives the total native
breakdown as cash plus portfolio minus liabilities with exact QUANTITY
arithmetic and requires equality with the supplied 5J-A total. It mirrors
5J-A availability exactly: unavailable cash always makes the total
unavailable; unavailable zero portfolio/liability may act as neutral only for
the calculation; and nonzero unavailable portfolio/liability makes the total
unavailable. Exact zero currency entries remain present. No FX conversion,
rounding, or missing-evidence inference occurs.

The internal 5J-D writer owns bounded complete `SERIALIZABLE` transaction
attempts and rejects caller-active sessions. The first SQL statement sets the
isolation level; a transaction advisory lock then serializes only the exact
`(userId, timestamp, currency, granularity)` key. The writer composes 5J-B and
5J-C inside that transaction before loading an existing target with
`FOR UPDATE`. Creation inserts, flushes, reloads, and verifies every physical
field. Exact state is a read-only replay; any scalar, metadata, JSONB,
NULL/empty, or deterministic-ID difference is a conflict with no update or
repair.

Serialization failure, deadlock, and concurrent unique violation restart the
whole operation at most three times after rollback. Evidence and domain
failures are never retried, and a unique violation alone is never replay
evidence. Source User, Account, membership, AccountSnapshot, and item rows are
read-only. Source-snapshot lineage remains ephemeral because the schema has no
lineage columns.

The thin 5J-E adapter exposes only
`POST /api/v1/net-worth/snapshots/recalculate`. It takes the target user solely
from `AuthenticatedPrincipal`, resolves output currency from the exact
persisted `User.baseCurrency`, commits the authentication/read transaction,
and invokes 5J-D once on the now-idle request session. The server owns an exact
UTC minute bucket, manual source, recalculation flag, and calculation version.
5J-B reloads the User inside SERIALIZABLE and rejects a stale command currency,
including a base-currency change between public preflight and the writer.

The endpoint has no body, path/query user selector, arbitrary currency, or
financial input. It returns only created/replayed identity metadata and counts;
source account/snapshot identities and financial evidence remain private.
Missing, ambiguous, unsupported, or corrupt source AccountSnapshots produce
one generic unavailable conflict, while physical target differences produce a
generic persisted-data conflict. The operation never creates missing account
snapshots and adds no scheduler, worker, background task, or historical read
API.

The cross-domain `snapshot_refresh` module begins with the pure 5K-A planning
boundary. It converts complete typed current user/account/membership evidence
into deterministic immutable account targets and one final net-worth
dependency target. Owner, admin, and editor targets are write-capable; viewer
targets are `reuse_only` and require an exact pre-existing AccountSnapshot.
One active unsupported bank, cash, or savings account invalidates the whole
plan. Consistently archived accounts are excluded, while contradictory archive
state fails closed.

Every target uses the User base currency as its required output currency and
preserves Account currency separately. Currency mismatch is classified as
requiring later exact FX evidence; 5K-A selects no rates and performs no
conversion. The final net-worth target declaratively depends on an exact
same-bucket, same-granularity, same-output-currency, same-version
AccountSnapshot for every active account, including `reuse_only` accounts.
The AccountSnapshot writer supports an explicit output currency, but the plan
does not invoke it. Execution/recovery, coordinated authorization, import hooks,
and scheduling belong to 5K-D and 5K-E.

The read-only 5K-B adapter requires a caller-owned `REPEATABLE READ` or
`SERIALIZABLE` transaction and verifies it before loading persisted evidence.
It reads the exact User plus every joined Account/AccountMember row, delegates
policy once to 5K-A, and partitions the immutable targets without changing
their modes. Persisted User owns base/output currency; AccountMember owns role,
relation, and acceptance.

Only viewer `reuse_only` targets trigger one batched exact AccountSnapshot
query by account IDs, bucket, granularity, User base currency, and calculation
version. Snapshot source and persistence timestamps are validated but need not
match the orchestration command. Owner/admin/editor targets never use existing
rows to bypass the future writer. 5K-B validates no financial fields; 5J-B
remains the complete AccountSnapshot financial authority. The repository uses
only autoflush-disabled reads, no locks, and no transaction or write methods.

The pure 5K-C1 extension separates persisted `Account.currency` from the
requested AccountSnapshot output currency. Required FX pairs come only from
actual selected price, Holding cost, cash, and liability currencies. Conversion
uses caller-supplied direct `native -> output` multiplication; inverse,
multi-hop, and fallback conversion are unsupported, and every supplied rate
must be consumed. Aggregate values use output currency while native breakdowns
retain their evidence currencies. Liability evidence must remain in Account
currency but may be converted to output currency; an empty mixed-currency
account consumes no synthetic rate.

The read-only 5K-C2 extension adds an optional output currency to the internal
AccountSnapshot evidence command. Omission retains exact Account-currency
behavior. Explicit output currency remains distinct from persisted
`Account.currency`; required direct pairs are derived only from actual current
and historical evidence currencies. Snapshot valuation selects latest direct
rates through the snapshot timestamp, while historical financial metrics select
from the same direct candidate pool through each event timestamp. Selected
snapshot and historical rate IDs remain separate deterministic audits.

Liability observations remain in Account currency and use one direct
Account-currency-to-output rate only when needed. The adapter remains
caller-transaction-owned and read-only and returns no ORM rows. Physical
projection mapping is owned by pure 5K-C3, writer identity/locking/replay by
5K-C4, and manual compatibility by 5K-C5.

The pure 5K-C3 projection uses the valuation output currency for every physical
AccountSnapshot scalar and for its existing deterministic identity. Changing
only output currency therefore changes the snapshot ID and all derived item
IDs. Investment items preserve native price/value/cost evidence while
converted value and cost fields use output currency. Native breakdowns remain
fixed-scale JSON and consumed direct rates remain in the existing version-1
exchange-rate audit.

Liability projection validates exactly one native breakdown. A same-currency
liability consumes no rate; a mixed-currency liability proves its scalar with
one direct native-to-output consumed rate, including an explicit zero
observation. The physical schema has no liability-native-breakdown column, so
that breakdown is validated but not copied into an unrelated JSONB field; the
selected liability identity remains nonphysical audit metadata. 5K-C3 creates
no ORM row, performs no I/O, and adds no migration.

The 5K-C4 writer extension accepts an optional canonical output currency.
Omission preserves Account-currency behavior. The resolved output currency is
used consistently by the unchanged advisory-lock algorithm, evidence command,
complete projected identity validation, and replay query. Different currencies
for the same account, timestamp, and granularity therefore coexist and replay
independently. Liability writes take the observation-table `SHARE` lock;
mixed-currency liabilities also take the existing market-evidence lock before
FX selection. The writer still owns exactly one outer transaction. Manual
orchestration composes its optional explicit currency in 5K-C5, while
coordinated execution remains 5K-D.

The 5K-C5 adapter keeps the existing route and response schema. Its optional
body accepts only `outputCurrency`; omission, `{}`, or null forwards `None`,
while an exact three-letter uppercase ASCII value is passed unchanged to the
writer. It performs no Account, User, or FX lookup and never substitutes
`User.baseCurrency`. Existing owner/admin/editor authorization, concealed
viewer/inaccessible behavior, authorization-transaction handoff, one-clock
minute bucket, and generic conflict mapping are unchanged. No API exposes FX
evidence, and coordinated User-base-currency execution remains 5K-D2.

The first coordinated-execution boundary is 5K-D1, an exact dependency guard
inside the existing net-worth evidence service and atomic writer. Both internal
commands may carry an already sorted immutable tuple of
`SelectedAccountSnapshotIdentity` values. `None` retains manual discovery of
all current active accounts; an explicit tuple, including an empty tuple,
requires exact persisted account and AccountSnapshot identity equality.

The evidence service never uses the guard to narrow discovery. Inside each
coherent writer attempt it reloads the persisted User, base currency, complete
Account/AccountMember access set, and exact source snapshots, then compares
both ordered account IDs and ordered account/snapshot identities. The writer
also compares the persistence audit identities before any replay or insert
decision. Every SERIALIZABLE retry receives the unchanged guard.

Selected dependency identities are returned by the internal writer result for
5K-D2 orchestration only. The manual endpoint passes `None` and exposes
neither account nor snapshot lineage. 5K-D1 adds no executor, outer
orchestration transaction, job state, schema, AccountSnapshot write, or API;
endpoint and import integration remain 5K-E.

The internal 5K-D2 `UserSnapshotRefreshExecutor` owns one short initial
`REPEATABLE READ` coverage transaction and calls 5K-B exactly once. It commits
that read before calling every deterministic owner/admin/editor refresh target
through the existing AccountSnapshot writer. Viewer targets never reach the
writer and contribute only their exact selected reusable identity. There is no
outer transaction across those writes: each account row commits independently,
and the existing bounded SERIALIZABLE NetWorth writer runs last.

The executor combines created, replayed, and reused AccountSnapshot identities
in the exact plan order and supplies them to the 5K-D1 guard. It validates every
dependency result and requires an idle session at each handoff. Partial failure
is resumable solely through persisted exact writer replay; no compensation,
repair, in-memory progress state, or job table exists. Account-set drift and
same-count substitution after coverage fail closed in the final writer, while
already committed account snapshots remain intact. 5K-D2 exposes no endpoint
and performs no authorization, import integration, scheduling, calculation,
evidence selection, physical comparison, or retry ownership; 5K-E remains the
public/import boundary.

5K-E is split into 5K-E1 (authorized synchronous manual endpoint) and 5K-E2
(import/post-processing integration). The E1 route is
`POST /api/v1/snapshot-refresh/recalculate`; it has no request body, path/query
selector, or caller-owned snapshot metadata. It derives the user only from
`CurrentPrincipal`, closes the authentication read transaction, verifies an
idle session, and invokes the 5K-D2 executor once with one server-owned UTC
minute bucket and the shared AccountSnapshot/NetWorth calculation version.
Persisted User state still owns output currency, and 5K-B/5K-D2 still own
membership roles and viewer `reuse_only` behavior.

The E1 response contains NetWorth identity/status, bucket metadata, currency,
aggregate account counts, and—since 5M-A—the exact manifest for the existing
5L portfolio and dashboard read APIs. The manifest copies calculation version
and the ordered `(account_id, snapshot_id)` tuple directly from the already
validated executor result. It performs no second database read, membership
account discovery, latest selection, sort, or fallback. Incomplete or
inconsistent lineage fails the complete result closed.

Every successful non-empty refresh manifest is directly compatible with both
unchanged 5L request contracts and must be transported without discovery,
sorting, or completion. A successful empty manifest has `accounts == []`,
zero selected and account-snapshot counts, and represents the complete
no-snapshot-capable-account state. It is not partial, erroneous, a fallback, or
a latest lookup. Because both 5L endpoints continue to require a non-empty
account set, the 5M-B adapter must expose an explicit empty-state branch, call
neither endpoint, and create no synthetic account selector.

Membership data, roles, refresh modes, writer dispositions, selected item
lineage, FX evidence, projections, and audits never cross the public boundary.
Incomplete state and immutable conflicts become separate generic HTTP 409
application errors. Independently committed account rows survive a later
failure and allow exact replay on a repeated request. E1 adds no scheduler,
worker, queue, background task, import hook, schema, or migration;
import/post-processing integration is implemented separately by 5K-E2.

5K-E2 adds an `imports`-owned post-processing orchestrator above the unchanged
canonical posting transaction. Posting commits first and returns immutable
persisted target counts. Investment-event imports then run the authorized
Holding rebuild; every nonempty import then invokes the whole-user coordinated
snapshot executor with `SnapshotSource.import_event` and the minute bucket
derived from the terminal batch `completedAt`. Each existing domain retains its
own transaction and commit.

Known Holding or snapshot incompleteness/conflict is therefore a truthful
post-commit outcome, not an import rollback: the existing import endpoint
returns HTTP 200 plus one aggregate `snapshot_refresh_status`. Deterministic
ImportLog rows are audit-only and use advisory-lock-protected UUIDv5 identity;
they do not suppress replay. No account/snapshot lineage is exposed and no
scheduler, queue, worker, background task, job table, schema change, or
compensation operation is introduced.

The final 5K audit verifies this complete chain against isolated PostgreSQL
databases and both public entry points. It confirms one non-inverted lock order
per writer path, domain-owned transactions with idle orchestration handoffs,
exact replay or immutable conflict, complete owner/editor/viewer lineage, and
the absence of cross-domain compensation. A manual and import refresh in the
same minute share the same physical identity; different immutable source
metadata conflicts without time shifting, update, or delete. The physical
catalog remains the existing 32-table, 28-enum schema with no 5K migration or
snapshot-refresh job table.
