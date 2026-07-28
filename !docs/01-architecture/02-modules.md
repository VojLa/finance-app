# Modules

The Python code is organized under `backend/python/app/modules`. A module owns
its API adapter, service layer, and repository where those exist; routers stay
thin and shared database infrastructure lives outside modules.

| Module                | Responsibility                                                                        | Status                                                                      |
| --------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `auth`                | Verify a trusted HS256 session-bridge token and resolve its user                      | Implemented                                                                 |
| `accounts`            | Account lifecycle, memberships, and invitations                                       | Implemented                                                                 |
| `liabilities`         | Canonical positive liability observations, atomic writes, and latest-as-of evidence   | 5I-L1/L2A implemented; consumed by snapshots in 5I-L2B                      |
| `imports`             | Register, upload, parse, normalize, and deduplicate CSV import batches                | Implemented through duplicate detection                                     |
| `portfolio`           | Read accessible accounts and holdings, convert cost values using latest FX            | Basic read endpoint implemented                                             |
| transactions          | Cash transaction lifecycle and classification                                         | Database schema only                                                        |
| ledger                | Investment events and movements                                                       | Database schema only                                                        |
| holdings              | Project and rebuild holdings from active canonical investment history                 | Pure projections, atomic writer, and authorized manual endpoint implemented |
| net_worth             | Pure aggregation, persisted evidence selection, physical projection, and atomic write | 5J-A–5J-C implemented; 5J-D after merge                                     |
| snapshots             | Exact account valuation, persistence, and authorized manual recalculation             | 5I-A–5I-E and liability integration implemented                             |
| prices / FX           | Provider refresh and price persistence                                                | Schema only; portfolio reads existing FX rows                               |
| dashboard / reporting | Dashboard read models                                                                 | Not implemented in Python                                                   |

`app/db/models` is a complete physical-schema mirror, grouped by domain. It is
not a service layer and it intentionally defines no ORM relationships, so
repository queries remain explicit and cannot trigger hidden asynchronous lazy
loads.

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
selecting evidence. It inserts one complete graph or performs an exact
read-only replay; persisted differences fail without repair. The public
snapshot adapter exposes only
`POST /api/v1/accounts/{account_id}/snapshots/recalculate`. A thin router
delegates to an application service that permits persisted owner/admin/editor
memberships, hides viewer/foreign/missing/archived accounts, closes the
authentication lookup transaction, and calls the atomic writer once on an idle
session. Server-owned minute-bucket metadata makes repeated calls within one
minute exact replays. Evidence/state failures and physical conflicts use generic
409 responses without exposing financial evidence.

For credit-card, loan, and mortgage accounts, the snapshot adapter composes the
canonical liability selector exactly once and bypasses Holdings, prices, FX,
Transactions, and investment history. The positive selected balance is stored
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
lineage columns. Public authorization and orchestration remain 5J-E.
