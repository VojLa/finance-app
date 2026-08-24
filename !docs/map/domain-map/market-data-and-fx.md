# Market data and FX map

ID: `DOM-MARKET`
Purpose: provider identity and persisted direct valuation evidence
Source of truth: aliases, price snapshots and exchange-rate observations

- Entry points: market services and operator alias/FX tools.
- Modules: `asset_aliases/`, `market_data/`, `prices/`, `fx/`.
- Depends on: assets and listings.
- Used by: valuation and portfolio history.
- Rules: [money and FX invariants](../../architecture/invariants/money-and-currency.md).
- Tests: [domain test matrix](../../domains/market-data-and-fx/testing.md).
- Details: [domain README](../../domains/market-data-and-fx/README.md).
