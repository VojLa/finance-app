# Investments and holdings testing

Type: testing
Status: current
Owns: representative investment atomicity, lineage and Holding verification
Code: investment, canonical-state and Holding tests
Update when: domain risks or representative suites change

| Risk                             | Invariant       | Unit/contract evidence                                     | Integration/E2E evidence                                   |
| -------------------------------- | --------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| Partial canonical event          | `INV-CANON-001` | `test_manual_investments.py`                               | `test_manual_investments_integration.py`                   |
| Duplicate lineage advance        | `INV-CANON-002` | `test_canonical_state.py`                                  | empty-holding and unknown-basis revision integration tests |
| Incorrect Holding math           | `INV-MONEY-001` | `test_holding_projection.py`, persistence projection tests | Holding persistence integration tests                      |
| Wrong Anycoin transfer basis     | `INV-MONEY-001` | `test_anycoin_transfer_valuation.py`, replay tests          | migration/schema parity and Holding integration tests      |
| Stale or partial Holding rebuild | `INV-CANON-003` | rebuild API/service tests                                  | `test_holding_rebuild_integration.py`                      |
| Browser-owned fallback           | `INV-AUTH-002`  | investment client/cutover tests                            | manual investment route integration                        |
