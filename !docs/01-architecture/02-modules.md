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
| holdings              | Project and rebuild holdings from active canonical investment history       | Pure projections and internal atomic writer implemented; public orchestration deferred |
| snapshots             | Account and net-worth snapshot rebuilding                                  | Database schema only                                |
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
Holding identity and one caller-supplied `TIMESTAMP(3)` value. The module has no
authorization or FastAPI boundary; those remain 5H-D.
