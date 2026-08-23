## Persisted account-currency valuation companions

R10-B1 uses the existing physical `AccountSnapshot` currency identity instead
of adding parallel summary columns or a companion table. A refresh for an
account with `Account.currency != User.baseCurrency` builds a primary snapshot
in the user base currency and a companion snapshot in the account currency.
They share account, timestamp, granularity, source, calculation version, and
canonical business evidence. A same-currency account writes only one physical
snapshot.

The snapshot writer owns the pair boundary. It acquires deterministic
currency-ordered identity locks, selects canonical evidence once, validates
both complete projections before inserting either, and commits both rows and
their items in one transaction. Replay validates both immutable identities.
The executor continues returning the primary identity, so NetWorth selects one
primary snapshot per active account and never counts companions as additional
accounts.

Account-currency calculation is a write-time snapshot capability. The ČNB
provider contract remains direct `foreign currency -> CZK`. Same-currency
components need no rate; foreign-to-CZK components consume one persisted
direct observation; CZK-to-foreign and foreign-to-foreign components consume
the required target-to-CZK or source-and-target-to-CZK observations. The
calculation performs one high-precision `Decimal` expression and requires the
final MONEY value to be exactly representable. It never creates a synthetic
provider observation such as `USD -> EUR`. Pivoted account-currency valuation
also requires every selected direct leg to have source ČNB; another persisted
provider fails closed.

The internal canonical `exchangeRates` audit remains version 1 for direct-only
primary snapshots. A pivoted companion uses version 2 and records exact
persisted IDs with direct, pivot-source, and pivot-target roles, including
event-date legs for historical metrics. Missing or invalid legs and
non-representable results fail closed before persistence.

The companion contains the full existing scalar and `AccountSnapshotItem`
contract in `Account.currency`. Native item and `*ByCurrency` evidence remains
native evidence. For liability accounts, the companion's physical
`liabilitiesValue` is the exact native/account-currency amount; no new
`liabilitiesValueByCurrency` column is required. Portfolio, dashboard, history,
OpenAPI, and generated frontend types are unchanged in R10-B1. R10-B2 owns the
future read/API/frontend presentation cutover.
