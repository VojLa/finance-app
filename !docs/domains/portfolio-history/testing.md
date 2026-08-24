# Portfolio-history testing

| Risk | Layer | Evidence |
| --- | --- | --- |
| Incomplete generation visible | publication integration | generation publication tests |
| Missing invalidation | service/integration | invalidation and scheduler tests |
| Replay corruption | repository/recovery | replay and rebuild tests |
| Schema mismatch | migration integration | `test_3q_portfolio_history_schema_migration_integration.py` |
