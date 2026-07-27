# Domain Model

The PostgreSQL schema contains 30 application tables. SQLAlchemy has a complete
mirror of that physical schema; this does not mean every domain has an API or
application service yet.

| Domain                 | Canonical records                                                      | Derived/read records                                         | Current Python use                            |
| ---------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| Identity and access    | `User`, `AccountMember`, `AccountInvite`                               | —                                                            | Implemented                                   |
| Accounts               | `Account`                                                              | —                                                            | Implemented                                   |
| Cash transactions      | `Transaction`, `TransactionPair`, `TransactionSplit`                   | —                                                            | Schema only                                   |
| Classification         | `Counterparty`, `CounterpartyAlias`, `Category`, `CategoryRule`        | —                                                            | Schema only                                   |
| Budgets                | `Budget` and related item/account/alert tables                         | —                                                            | Schema only                                   |
| Assets and market data | `Asset`, `AssetListing`, `AssetAlias`, `PriceSnapshot`, `ExchangeRate` | prices and FX                                                | FX is read by portfolio                       |
| Investment ledger      | `InvestmentEvent`, `InvestmentMovement`                                | —                                                            | Schema only                                   |
| Portfolio              | —                                                                      | `Holding`                                                    | Read by portfolio; deterministic rebuild and authorized manual endpoint implemented |
| Imports                | `ImportBatch`, `ImportRow`, `ImportLog`                                | parse, normalization, and duplicate state                    | Implemented through duplicate detection       |
| Snapshots              | —                                                                      | `AccountSnapshot`, `AccountSnapshotItem`, `NetWorthSnapshot` | Schema only                                   |

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
only apply later events. These are documented invariants; the rebuilding
workflow is not implemented yet.
