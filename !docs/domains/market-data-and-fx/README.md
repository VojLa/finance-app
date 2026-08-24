# Market data and FX

Type: domain
Status: current
Owns: provider identity, asset aliases, prices, direct FX and requirements
Code: `asset_aliases/`, `market_data/`, `prices/`, `fx/`
Update when: provider, market requirement, alias or valuation evidence changes

Aliases and persisted direct price/FX observations are valuation evidence. They do not own holdings, account access or portfolio totals. Missing, stale, future, wrong-direction, conflicting or synthetic evidence fails closed.

Verification: [test matrix](testing.md). Operations: [provider identity](../../operations/provider-identity.md).
