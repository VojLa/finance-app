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
