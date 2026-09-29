# Market data and FX modules

Type: module
Status: current
Owns: provider identity, evidence acquisition and validation runtime layers
Code: `asset_aliases/`, `market_data/`, `prices/`, `fx/`
Update when: a provider, evidence layer or dependency changes

| Module                | Responsibility                                                           | Main layers and entry points                                             |
| --------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `asset_aliases`       | exact external identity and create-only onboarding                       | identity, service, repository and models                                 |
| `market_data`         | requirements, provider selection, evidence source policy and persistence | factory, policy, requirements, service, writer and repositories          |
| `market_data/history` | historical range selection and provider adapters                         | range/selection models, factory and CoinGecko/Twelve Data/local adapters |
| `prices`              | price provider identity, transport, parsing and validation               | CoinGecko, Twelve Data and Yahoo provider stacks                         |
| `fx`                  | direct FX transport, parsing and validation                              | Twelve Data and Yahoo provider stacks                                    |

These modules depend on configured provider clients, exact asset identity and
PostgreSQL evidence stores. They cannot infer an alias, synthesize cross rates or
publish a valuation. Exact files are in the [code inventory](../../map/generated/CODE-INVENTORY.md).

For canonical history, Twelve Data listed-price and direct-FX adapters retain the
provider's completed 30-minute UTC close timestamps even when a daily or coarser
portfolio point consumes them. The request interval is evidence granularity, not a
portfolio-resolution label; daily relabeling, repeated closes, inverse/pivot FX and
source fallback remain prohibited. Provider query bounds are translated from the
required close-time window to bar-open time, excluding a bar that cannot close by the
valuation timestamp.
