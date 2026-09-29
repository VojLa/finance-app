# ADR 0014 - Exact Anycoin BTC display identity

Status: Accepted
Date: 2026-08-19
Decision owners: Finance application architecture
Supersedes: none
Superseded by: none

## Kontext

The real Anycoin export carries type, order, timestamp, amount, currency, and
transaction ID, but no asset display name. Its exact crypto symbol is still
canonical source evidence. Portfolio snapshot readers require a nonblank
`Asset.name`, so a clean BTC import with `Asset.name = NULL` could publish a
snapshot that neither the portfolio nor dashboard read model could expose.

Ticker title-casing and provider discovery are not accepted identity evidence.
The fix must also preserve the one existing BTC/CZK Asset and Listing across
replay and concurrent posting.

## Rozhodnuti

The imports boundary owns one closed display mapping:

```text
(ImportSource.anycoin, AssetType.crypto, normalized symbol BTC)
-> Asset.name Bitcoin
```

Anycoin normalization writes that exact name for future BTC rows. The posting
plan applies the same mapping to already persisted normalized BTC rows whose
source name is `NULL`. Under the existing provider advisory lock and row lock,
asset resolution enriches an existing exact Anycoin BTC Asset only when its
name is `NULL`. `Bitcoin` replays unchanged; every other non-NULL name fails
without rename or repoint.

Non-BTC Anycoin symbols receive no display name. Any supplied non-BTC name,
generic title-casing, symbol map, alias lookup, provider request, or rename is
rejected. The separate ADR 0013 allowlist remains the sole CoinGecko alias
mapping and does not act as a display-name discovery mechanism.

## Dusledky

- Clean and legacy-NULL Anycoin BTC identities produce portfolio and dashboard
  read models with the exact display name `Bitcoin`.
- Posting replay and concurrent resolution converge on the same Asset/Listing.
- A conflicting historical name fails closed for operator review rather than
  silently changing canonical identity.
- Supporting another source or symbol requires a new explicit decision and
  source tests.

## Migracni nebo rollout plan

No schema migration or bulk rename is required. Exact legacy NULL rows are
enriched transactionally on their next canonical Anycoin BTC posting replay.
Conflicting non-NULL rows are intentionally not repaired automatically.
