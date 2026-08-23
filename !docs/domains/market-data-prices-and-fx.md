# Market data, prices, and FX

## Scope and source of truth

Asset/provider aliases and persisted direct price/FX observations are reference
evidence for valuation. They do not own user holdings, event history, account
access, or portfolio totals.

## Responsibilities and boundaries

- Maintain immutable provider identity and exact asset/listing aliases.
- Define market requirements and acquire/persist selected provider observations.
- Support direct price and FX evidence for snapshots/current value.
- Expose server-operator tools for safe alias onboarding and FX audit.

Implementation is in `asset_aliases/`,
`market_data/{requirements,service,writer}.py`, `market_data/history/`,
`prices/providers/`, and `fx/`. Operator tools include
`backend/python/scripts/asset_alias.py` and `audit_exchange_rates.py`.
Snapshots request evidence through application services; no browser route owns
finance provider interaction.

## Invariants

- Provider identity is explicit and immutable.
- Valuation uses selected persisted direct observations only.
- Never silently invert, triangulate, or synthesize FX pairs.
- Missing, stale, future, wrong-direction, wrong-source, conflicting, or
  non-representable evidence fails closed at the valuation boundary.
- Historical event conversion and current valuation have different as-of rules.

Tests include `test_asset_alias_*`, `test_market_data_*`,
`test_market_evidence_*`, `test_*price_*`, `test_*fx_*`, and provider tests.
Read [FX reconciliation](../04-development/04-fx-reconciliation.md) and
[decision 0008](../05-decisions/0008-direct-twelve-data-fx.md).
