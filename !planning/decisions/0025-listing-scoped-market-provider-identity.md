# ADR 0025 – Listing-scoped market-provider identity

Status: Accepted
Date: 2026-09-30
Decision owners: vlastník FinanceApp
Supersedes in part: ADR 0023 for Yahoo identity storage

## Kontext

`Asset` represents the economic instrument and `AssetListing` the concrete
tradable quotation. Existing `AssetAlias` rows are attached only to `Asset`, so
one Yahoo alias cannot distinguish two Yahoo symbols for two listings of the
same instrument. `PriceSnapshot` also lacks the provider symbol used to acquire
the observation. A recent price can therefore lose the identity lineage needed
to prove that it still belongs to the currently resolved listing.

The existing investment ledger, Holding projection, market-evidence writer and
valuation pipeline remain authoritative and must not be duplicated.

## Rozhodnutí

- `Asset != AssetListing != provider symbol` is an explicit invariant.
- `AssetListing.exchange` remains the human-readable venue value and
  `AssetListing.mic` remains the optional standardized exchange code. Crypto
  pairs do not require a fabricated MIC.
- `AssetAlias` gains an optional `listingId`. Yahoo aliases created for market
  acquisition are listing-scoped. Asset-scoped aliases remain valid only for
  providers whose identity is genuinely asset-wide, and as transitional legacy
  evidence where one listing makes the mapping deterministic.
- An explicit `AssetListing.provider/providerSymbol` remains a valid direct
  identity. The central resolver prefers that direct identity, otherwise it
  requires exactly one compatible listing-scoped alias. It never constructs a
  Yahoo symbol by stripping or appending a suffix during valuation.
- Existing aliases are backfilled with `listingId` only when their Asset has
  exactly one listing. Ambiguous aliases remain unresolved.
- `PriceSnapshot` persists the exact provider symbol used for acquisition.
  Valuation accepts price evidence only when listing, source, provider symbol,
  native currency and freshness all match the current requirement.
- `AssetListing.basePriority` stores a static future preference. Provider health
  is deliberately not represented by this value and is not implemented here.
- Yahoo suffix mappings may support explicit onboarding suggestions or
  validation, but persisted `providerSymbol` is authoritative and is never
  overwritten by a heuristic.

## Důsledky

- The same Asset can safely have multiple listings with different Yahoo symbols.
- A provider failure cannot mutate listing priority or silently select another
  listing.
- Existing unambiguous data is preserved; ambiguous data fails closed for
  operator review.
- `PriceSnapshot` remains a native-currency observation. FX conversion continues
  only in valuation.
- ADR 0023's closed Trading 212 allowlist remains valid, but Yahoo entries are
  written as listing-scoped identities instead of asset-only identities.

## Odložené části

This decision does not implement provider/listing health, automatic fallback,
exchange calendars, retry/backoff policy, or a general security master. Those
remain a separate stage after the Yahoo vertical slice is proven.
