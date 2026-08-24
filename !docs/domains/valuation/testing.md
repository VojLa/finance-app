# Valuation testing

| Risk | Invariant | Evidence |
| --- | --- | --- |
| Currency mismatch | `INV-CURRENCY-001` | account snapshot and currency tests |
| Invalid baseline | `INV-CANON-003` | daily-baseline/current-value tests |
| Partial publication | `INV-PUBLISH-001` | snapshot refresh integration tests |
| Decimal drift | `INV-MONEY-001` | snapshot, net-worth and public money tests |
