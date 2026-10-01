# Market data and FX testing

Type: testing
Status: current
Owns: representative provider identity, transport and evidence-policy verification
Code: alias, market-data, price, FX and historical-provider tests
Update when: provider risks or representative suites change

| Risk                                      | Invariant                  | Unit/fixture evidence                                    | Integration/E2E evidence                                 |
| ----------------------------------------- | -------------------------- | -------------------------------------------------------- | -------------------------------------------------------- |
| Wrong provider identity                   | `INV-FX-002`               | asset-alias identity/service/CLI tests                   | alias onboarding and provider-identity integration tests |
| Synthetic, stale or wrong-source evidence | `INV-FX-001`, `INV-FX-002` | market policy/source-policy tests                        | market-data requirements and writer integration tests    |
| Provider payload or transport drift       | `INV-INPUT-001`            | provider factory/parser/transport suites                 | CoinGecko/Twelve Data market-data integration suites     |
| Historical range gap                      | `INV-HISTORY-002`          | `test_historical_market_data.py`, provider history tests | history generation builder/publication tests             |
| Exchange-rate source drift                | `INV-FX-002`               | `test_exchange_rate_audit_script.py`                     | Twelve Data FX snapshot E2E test                         |
| Yahoo suffix/native-currency drift        | `INV-FX-002`               | Yahoo provider, exchange mapping and requirements tests  | market writer and snapshot evidence tests                |
| Listing identity reused across accounts   | `INV-FX-002`               | requirement deduplication tests                          | writer replay and snapshot valuation tests               |
| Runtime failure mutates static priority   | ADR 0026                    | health state-machine and listing-selector tests          | persisted health concurrency test                        |
| Unsafe same-ticker fallback               | `INV-FX-002`, ADR 0026      | selector foreign-Asset/currency/MIC conflict tests       | current-value and snapshot fallback integration tests    |
| Retry storm or stale worker completion    | ADR 0026                    | bounded retry and ordered-outcome tests                  | lease/restart/concurrent-worker PostgreSQL test           |
| Closed market treated as provider failure | ADR 0026                    | eight-MIC calendar and freshness tests                   | snapshot evidence previous-close tests                   |
| Unreviewed global alias mutation          | `INV-INPUT-001`, ADR 0026   | operator CLI and audit service tests                     | append-only alias audit integration tests                |

Yahoo fixture coverage includes AAPL/USD, VWCE.DE/EUR, CEZ.PR/CZK, VUSA.L/GBP,
NESN.SW/CHF and BTC-USD/USD, plus unknown/partial responses, stale data, currency
conflicts, ambiguous listings and exact replay.

Selector coverage includes priority, degraded fallback, recovery, deterministic
ties, foreign Asset rejection, incompatible currency, exact Yahoo/CoinGecko/Twelve
identities and one actual fallback price shared safely by multiple requested holdings.
