# Market data and FX

Type: domain
Status: current
Owns: provider identity, asset aliases, prices, direct FX and requirements
Code: `asset_aliases/`, `market_data/`, `prices/`, `fx/`
Update when: provider, market requirement, alias or valuation evidence changes

An Asset is the economic instrument, an AssetListing is one tradeable venue and
currency, and a provider symbol is the provider-specific identity of that listing.
They are not interchangeable. Aliases and persisted direct price/FX observations
are valuation evidence. They do not own holdings, account access or portfolio
totals. Missing, stale, future, wrong-direction, conflicting or synthetic evidence
fails closed.

## Capabilities and boundaries

- maintain exact listing-scoped Yahoo identities without ticker or suffix inference;
- order same-Asset listings by immutable `basePriority`, filter them by persisted
  runtime health and period availability, and select one with an explicit stable
  tie-breaker;
- fall back only to another exact listing of the same Asset and automatically return
  to the preferred listing after valid evidence restores its health;
- retain the exact provider symbol and native listing currency on price evidence;
- identify required market observations for valuation work;
- fetch, validate and persist direct prices and FX observations;
- select historical price evidence through explicit provider/range policy;
- audit persisted exchange-rate source identity without repairing data.

The domain supplies evidence; valuation decides whether that evidence satisfies a
specific calculation.

`basePriority` is static catalogue preference. `MarketDataListingHealth` is separate
operational state for one listing/provider identity and owns leases, cooldown,
failure classification and success/failure counters. Neither health nor fallback
changes Asset, Holding, cost basis, historical prices, or priority. The deterministic
path is:

`Asset → listings ordered by basePriority → health/availability filtering → selected listing → exact provider identity → native price evidence → direct FX evidence → valuation`.

The non-production `local_free` policy uses Yahoo for listed securities and direct
FX, while crypto holdings use their exact CoinGecko asset alias in the listing's
native currency. Yahoo crypto pairs such as `BTC-USD` remain supported for an
explicit USD crypto listing, but are not attached to a CZK/EUR broker listing.
Anycoin event-date transfer valuation therefore cites a separate native-USD
`BTC-USD` Yahoo reference listing plus explicit USD/CZK FX; its current CZK market
price remains CoinGecko evidence on the Anycoin listing. The two listing identities
share the Bitcoin Asset but are never interchangeable.

Persisted FX observations are immutable. If Yahoo later revises the value for the
same exact pair, source and effective timestamp, automatic scheduled/price refresh
and explicit manual recalculation retain the first persisted observation and log
the revision instead of blocking publication or rewriting history. Other write
paths reject the conflict.

For local Yahoo verification, a persisted `AssetListing.providerSymbol` is the
authority. A listing-scoped `AssetAlias` is the secondary exact mapping. Legacy
asset-wide Yahoo aliases are usable only when the Asset has exactly one listing;
ambiguous identities remain unresolved. The small MIC-to-suffix catalogue is for
assisted onboarding and validation only and never rewrites an explicit symbol.

Regular-session calendars are explicit for XNAS, XNYS, ARCX, XETR, XLON, XPRA,
XSWX and XTKS. They distinguish a supported prior close, weekend and holiday from
actually stale evidence. Crypto has no exchange calendar and every other MIC remains
`unknown_calendar`.

Health is never replaced by a separate provider-wide guessed state. A provider rate
limit is enforced across its exact listing rows through persisted cooldown evidence.
After a recoverable cooldown, acquisition may probe the preferred listing, while
valuation keeps using the safe fallback until price persistence succeeds. For a
supported closed session, an exact fresh previous close suppresses unnecessary
provider I/O; unknown calendars never do. A sanitized provider `Retry-After` value
can extend the durable cooldown.

## Navigation

- [Module and provider map](modules.md)
- [Market evidence flow](../../architecture/flows/market-evidence.md)
- [Money and FX invariants](../../architecture/invariants/money-and-currency.md)
- [Provider identity runbook](../../operations/provider-identity.md)
- [Test matrix](testing.md)
