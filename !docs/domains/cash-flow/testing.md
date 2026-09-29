# Cash-flow testing

Type: testing
Status: current
Owns: representative cash-write, classification and operational projection verification
Code: cash-flow backend and frontend tests
Update when: domain risks or representative suites change

| Risk                                 | Invariant                        | Unit/contract evidence                   | Integration/frontend evidence                            |
| ------------------------------------ | -------------------------------- | ---------------------------------------- | -------------------------------------------------------- |
| Duplicate or unauthorized cash write | `INV-CANON-001`, `INV-CANON-002` | `test_transactions_categories.py`        | `test_transactions_categories_integration.py`            |
| Incorrect operational visibility     | `INV-CANON-003`                  | transaction visibility tests             | `test_operational_transaction_visibility_integration.py` |
| Budget/dashboard aggregation drift   | `INV-MONEY-001`                  | `test_budgets_operational_dashboard.py`  | `test_budgets_operational_dashboard_integration.py`      |
| Browser contract fallback            | `INV-AUTH-002`                   | transaction/category/budget client tests | operational-dashboard model and cutover tests            |
