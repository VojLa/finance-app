# Market evidence flow

Type: flow
Status: current
Owns: exact provider identity and untrusted payload to persisted price/FX evidence
Code: asset aliases, market data, price/FX providers and evidence writers
Update when: provider identity, selection, validation or persistence changes

1. A valuation or history plan starts from the Holding's requested `AssetListing`
   and declares the exact price/FX observations it needs,
   including the provider's explicit price quote currency separately from the
   acquisition/listing cost currency.
2. The central selector considers only listings of that same Asset and asset type.
   It requires a known native currency, exact provider identity, period availability,
   a usable health/cooldown tier and a safe currency path. It then sorts by health
   tier, descending immutable `basePriority`, provider, provider symbol, MIC and ID.
3. The selected AssetListing resolves its direct provider identity or one
   listing-scoped provider alias. A legacy asset-wide alias is accepted only for a
   proven single-listing Asset; no ticker/suffix inference or provider discovery occurs.
4. A persisted lease is committed before the selected provider transport performs
   bounded I/O. Retry is limited; sanitized `Retry-After`, cooldown and provider
   rate limits survive restarts. An expired recoverable cooldown permits an
   acquisition probe, not immediate reuse for valuation.
5. Provider-specific parsing and common validation reject malformed, stale, future,
   wrong-direction or conflicting evidence.
6. The writer persists the actual selected listing ID, source, exact provider symbol,
   native currency,
   observation timestamp, fetch/create timestamp and applicable lineage. The exact
   listing/provider health success is finalized in that same transaction after the
   evidence write. If the worker no longer owns the persisted lease, the entire
   evidence transaction rolls back; an expired worker cannot publish a late price.
7. Valuation/history maps that evidence back to the requested Holding without
   relabelling the price, then reselects FX under its cutoff and publication
   rules. Price-value and cost-basis currencies retain separate lineage and each
   requires its own direct conversion to the account/output currency; a missing
   requirement remains unavailable.

One Asset may contribute evidence through different exact listings. In particular,
an Anycoin BTC transfer uses its CZK exchange listing for the holding, a separate
Yahoo `BTC-USD` native-USD reference listing for event-date acquisition evidence,
and explicit USD/CZK FX. A USD price is never persisted against the CZK listing.

Transport failure is retryable but never authorizes a synthetic rate or price.
When a supported exchange is closed, an exact acceptable previous close can satisfy
the acquisition plan without a provider call. An unknown calendar never enables
that shortcut. A missing provider symbol becomes an explicit health failure only
when the provider is already configured; an unknown provider remains unresolved.
Operator alias changes follow the [provider runbook](../../operations/provider-identity.md).

Scheduled, price-refresh and explicit manual-recalculation runs may encounter a
provider revision for an FX observation whose exact pair, source and effective
timestamp were already persisted. Because that identity is immutable, these runs
retain and reuse the existing row, record the revision conflict, and never overwrite
the rate. Import and holdings-recalculation flows continue to fail closed on the
same conflict.

The complete ownership path is:

`InvestmentEvent + InvestmentMovement → Holding → Asset → requested AssetListing → health-aware selected AssetListing → provider identity → PriceSnapshot → FX evidence → valuation → portfolio snapshot`.
