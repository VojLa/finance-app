# Modules

The Python code is organized under `backend/python/app/modules`. A module owns
its API adapter, service layer, and repository where those exist; routers stay
thin and shared database infrastructure lives outside modules.

| Module                | Responsibility                                                             | Status                                              |
| --------------------- | -------------------------------------------------------------------------- | --------------------------------------------------- |
| `auth`                | Verify a trusted HS256 session-bridge token and resolve its user           | Implemented                                         |
| `accounts`            | Account lifecycle, memberships, and invitations                            | Implemented                                         |
| `liabilities`         | Canonical positive liability observations, atomic writes, and latest-as-of evidence | 5I-L1 selection and 5I-L2A internal writer implemented |
| `imports`             | Register, upload, parse, normalize, and deduplicate CSV import batches     | Implemented through duplicate detection             |
| `portfolio`           | Read accessible accounts and holdings, convert cost values using latest FX | Basic read endpoint implemented                     |
| transactions          | Cash transaction lifecycle and classification                              | Database schema only                                |
| ledger                | Investment events and movements                                            | Database schema only                                |
| holdings              | Project and rebuild holdings from active canonical investment history       | Pure projections, atomic writer, and authorized manual endpoint implemented |
| snapshots             | Exact account valuation, persistence, and authorized manual recalculation       | 5I-A–5I-E implemented; liability integration deferred |
| prices / FX           | Provider refresh and price persistence                                     | Schema only; portfolio reads existing FX rows       |
| dashboard / reporting | Dashboard read models                                                      | Not implemented in Python                           |

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

The `liabilities` module exposes a caller-transaction-owned, read-only
latest-as-of selector and an internal transaction-owning append writer over
canonical `LiabilityBalance` observations. Both validate supported account
type, account currency, exact MONEY components, the total formula, and
timestamp precision. The writer locks the Account, then sorted
timestamp/source and optional external-identity transaction advisory scopes,
and inserts one deterministic UUIDv5 row or validates an exact read-only
replay. Conflicts are never updated or repaired; any failure rolls back the
single writer-owned transaction. Neither boundary derives debt from ordinary
Transactions or falls back to zero. No public liability endpoint exists, and
5I snapshot integration remains deferred to 5I-L2B.

Authorization is established at request time under the current application
contract; the Account itself is revalidated by the writer under lock, while a
membership revocation between authorization and writer commit remains a
documented narrow race. Canonical liability evidence selection exists in
5I-L1 and the internal atomic observation writer in 5I-L2A, while
authorization/import and snapshot integration remain deferred to 5I-L2B.
`NetWorthSnapshot` remains outside Step 5I.
