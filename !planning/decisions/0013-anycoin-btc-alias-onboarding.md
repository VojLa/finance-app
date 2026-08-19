# ADR 0013 - Exact Anycoin BTC alias onboarding

Status: Accepted
Date: 2026-08-19
Decision owners: Finance application architecture
Supersedes: none
Superseded by: none

## Kontext

Market acquisition accepts crypto identity only through an exact persisted
CoinGecko `AssetAlias`. The generic alias workflow deliberately requires an
operator and never guesses from a ticker. A clean Anycoin BTC import therefore
created the canonical ledger and Holding, but could not acquire a BTC price
until an operator added the globally known CoinGecko identity `bitcoin`.

Anycoin's normalized import contract already supplies an exact source, exact
crypto type, and normalized BTC symbol. This is narrower evidence than a generic
ticker lookup and can be handled deterministically without provider discovery.

## Rozhodnuti

Durable import finalization owns one closed allowlist:

```text
(ImportSource.anycoin, AssetType.crypto, normalized symbol BTC)
-> (AssetAliasProvider.coingecko, external_id bitcoin)
```

The boundary runs only after all canonical posting/replay has committed and
before Holdings rebuild and market acquisition. It reads asset movements only
for the exact account and sorted batch set. A BTC candidate must point to one
canonical crypto Asset and its exact Anycoin exchange Listing. Zero valid BTC
identity, multiple BTC Assets, wrong canonical state, or an immutable alias
conflict fails before provider HTTP.

Persistence remains exclusively in the existing `AssetAliasWriter`, including
its deterministic UUID, dual advisory locks, `SERIALIZABLE` transaction, retry
policy, physical reload, replay, and conflict checks. No migration, public API,
second writer, or direct `AssetAlias` construction is introduced.

Non-BTC symbols, including ETH and WBTC, receive no automatic alias. There is no
case repair, symbol guessing, provider catalog request, Yahoo identity, inverse,
pivot, or fallback.

## Dusledky

- A clean Anycoin BTC durable job can acquire its CoinGecko price in the same
  finalization attempt.
- Worker crash/replay and concurrent finalization converge on one immutable
  alias row.
- Corrupt or conflicting identity state cannot be silently reassigned.
- Adding another source, symbol, asset type, or external identity requires a new
  explicit decision and tests; this ADR is not a generic mapping registry.

## Zamitnute alternativy

- Generic `symbol -> provider ID` lookup: rejected because tickers are not
  globally unique provider identities.
- CoinGecko discovery HTTP: rejected because provider search results are not
  canonical import evidence.
- Creating aliases in parsing, normalization, posting, Holdings, or market
  planning: rejected because those stages do not own the immutable alias writer.
- Falling back to Yahoo or a currency pivot: rejected because it changes the
  provider and identity contract instead of resolving it.

## Migracni nebo rollout plan

No schema migration is required. Existing clean Anycoin BTC batches acquire the
alias on the next exact durable finalization replay. Existing exact aliases
replay unchanged; conflicting aliases fail closed and require operator review.
