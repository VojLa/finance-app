# Modules

The Python code is organized under `backend/python/app/modules`. A module owns
its API adapter, service layer, and repository where those exist; routers stay
thin and shared database infrastructure lives outside modules.

| Module                | Responsibility                                                             | Status                                              |
| --------------------- | -------------------------------------------------------------------------- | --------------------------------------------------- |
| `auth`                | Verify a trusted HS256 session-bridge token and resolve its user           | Implemented                                         |
| `accounts`            | Account lifecycle, memberships, and invitations                            | Implemented                                         |
| `imports`             | Register, upload, parse, normalize, and deduplicate CSV import batches     | Implemented through duplicate detection             |
| `portfolio`           | Read accessible accounts and holdings, convert cost values using latest FX | Basic read endpoint implemented                     |
| transactions          | Cash transaction lifecycle and classification                              | Database schema only                                |
| ledger                | Investment events and movements                                            | Database schema only                                |
| holdings              | Project and rebuild holdings from active canonical investment history       | Pure projections, atomic writer, and authorized manual endpoint implemented |
| snapshots             | Exact account valuation evidence and future snapshot persistence             | 5I-A valuation plus 5I-B read-only evidence selection implemented |
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

The Python `snapshots` module owns the pure 5I-A valuation contract and the
read-only, caller-transaction-owned 5I-B persisted-evidence adapter. The adapter
selects latest unambiguous persisted prices and direct FX, derives active
account-type-specific balances, and derives lifetime financial metrics only
where persisted classifications prove completeness, then delegates valuation
arithmetic to 5I-A. Cash-account net deposits, realized investment P/L, fees,
and taxes are tagged unsupported rather than silently zeroed because persisted
evidence does not prove them complete. Cash-account unrealized P/L is
structurally zero because Holdings are forbidden. It writes no snapshot rows
and owns no transaction.
Physical projection/writing/public orchestration remain 5I-C–5I-E;
canonical liability balance support is deferred to 5I-L, and
`NetWorthSnapshot` remains outside Step 5I.
