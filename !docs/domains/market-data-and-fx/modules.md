# Market data and FX modules

Type: module
Status: current
Owns: provider identity, evidence acquisition and validation runtime layers
Code: `asset_aliases/`, `market_data/`, `prices/`, `fx/`
Update when: a provider, evidence layer or dependency changes

| Module                | Responsibility                                                           | Main layers and entry points                                             |
| --------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `asset_aliases`       | exact external identity, audited operator resolution and explicit listing creation | identity, service, repository, CLI and audit model                 |
| `market_data`         | central listing selection, persisted health/leases, calendars, retry, requirements and evidence persistence | selector, health, calendar, factory, service, writer and repositories |
| `market_data/history` | historical range selection and provider adapters                         | range/selection models, factory and CoinGecko/Twelve Data/local adapters |
| `prices`              | price provider identity, transport, parsing and validation               | CoinGecko, Twelve Data and Yahoo provider stacks                         |
| `fx`                  | direct FX transport, parsing and validation                              | Twelve Data and Yahoo provider stacks                                    |

These modules depend on configured provider clients, exact asset identity and
PostgreSQL evidence stores. They cannot infer an alias, synthesize cross rates or
publish a valuation. Exact files are in the [code inventory](../../map/generated/CODE-INVENTORY.md).

Yahoo listed-price acquisition consumes one resolved listing identity: listing ID,
exact provider symbol, native currency and asset type. The parser requires an exact
response symbol, matching currency, a positive price, valid timestamp and minute
granularity. `PriceSnapshot.providerSymbol` preserves that lineage. FX conversion is
not part of the Yahoo price adapter.

For canonical history, Twelve Data listed-price and direct-FX adapters retain the
provider's completed 30-minute UTC close timestamps even when a daily or coarser
portfolio point consumes them. The request interval is evidence granularity, not a
portfolio-resolution label; daily relabeling, repeated closes, inverse/pivot FX and
source fallback remain prohibited. Provider query bounds are translated from the
required close-time window to bar-open time, excluding a bar that cannot close by the
valuation timestamp.
