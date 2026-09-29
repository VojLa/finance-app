# Valuation testing

Type: testing
Status: current
Owns: representative snapshot, baseline, current-value and net-worth verification
Code: valuation and snapshot-refresh tests
Update when: valuation risks or representative suites change

| Risk                                 | Invariant                           | Unit/contract evidence                             | Integration/E2E evidence                            |
| ------------------------------------ | ----------------------------------- | -------------------------------------------------- | --------------------------------------------------- |
| Currency or rounding drift           | `INV-CURRENCY-001`, `INV-MONEY-001` | snapshot calculation/rounding and currency suites  | account snapshot evidence integration tests         |
| Invalid baseline or cutoff           | `INV-VALUE-001`                     | daily-baseline and current-value projection suites | current-value/baseline integration tests            |
| Stale or conflicting market evidence | `INV-VALUE-002`, `INV-FX-002`       | market-evidence freshness/source tests             | market-backed snapshot refresh integration tests    |
| Partial refresh publication          | `INV-PUBLISH-001`                   | refresh plan/executor/service tests                | refresh evidence and final-audit integration suites |
| Incorrect liability net worth        | `INV-VALUE-003`                     | net-worth projection/evidence tests                | net-worth persistence integration tests             |
