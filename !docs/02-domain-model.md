# Domain Model

The PostgreSQL schema contains 30 application tables. SQLAlchemy has a complete
mirror of that physical schema; this does not mean every domain has an API or
application service yet.

| Domain | Canonical records | Derived/read records | Current Python use |
| --- | --- | --- | --- |
| Identity and access | `User`, `AccountMember`, `AccountInvite` | — | Implemented |
| Accounts | `Account` | — | Implemented |
| Cash transactions | `Transaction`, `TransactionPair`, `TransactionSplit` | — | Schema only |
| Classification | `Counterparty`, `CounterpartyAlias`, `Category`, `CategoryRule` | — | Schema only |
| Budgets | `Budget` and related item/account/alert tables | — | Schema only |
| Assets and market data | `Asset`, `AssetListing`, `AssetAlias`, `PriceSnapshot`, `ExchangeRate` | prices and FX | FX is read by portfolio |
| Investment ledger | `InvestmentEvent`, `InvestmentMovement` | — | Schema only |
| Portfolio | — | `Holding` | Read by portfolio; rebuild is not implemented |
| Imports | `ImportBatch`, `ImportRow`, `ImportLog` | parse and normalization state | Implemented through normalization |
| Snapshots | — | `AccountSnapshot`, `AccountSnapshotItem`, `NetWorthSnapshot` | Schema only |

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
  candidate deduplication key.
- Holdings and snapshots are rebuildable read models. They must never replace
  transactions or ledger events as the historical source of truth.

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
