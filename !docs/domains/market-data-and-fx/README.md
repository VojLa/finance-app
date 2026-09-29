# Market data and FX

Type: domain
Status: current
Owns: provider identity, asset aliases, prices, direct FX and requirements
Code: `asset_aliases/`, `market_data/`, `prices/`, `fx/`
Update when: provider, market requirement, alias or valuation evidence changes

Aliases and persisted direct price/FX observations are valuation evidence. They do not own holdings, account access or portfolio totals. Missing, stale, future, wrong-direction, conflicting or synthetic evidence fails closed.

## Capabilities and boundaries

- maintain exact provider aliases without ticker-based inference;
- identify required market observations for valuation work;
- fetch, validate and persist direct prices and FX observations;
- select historical price evidence through explicit provider/range policy;
- audit persisted exchange-rate source identity without repairing data.

The domain supplies evidence; valuation decides whether that evidence satisfies a
specific calculation.

## Navigation

- [Module and provider map](modules.md)
- [Market evidence flow](../../architecture/flows/market-evidence.md)
- [Money and FX invariants](../../architecture/invariants/money-and-currency.md)
- [Provider identity runbook](../../operations/provider-identity.md)
- [Test matrix](testing.md)
