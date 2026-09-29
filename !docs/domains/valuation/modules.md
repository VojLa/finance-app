# Valuation modules

Type: module
Status: current
Owns: snapshot, baseline, current-value, net-worth and refresh runtime layers
Code: valuation Python modules
Update when: a valuation layer, entry point or dependency changes

| Module             | Responsibility                                              | Main layers and entry points                                               |
| ------------------ | ----------------------------------------------------------- | -------------------------------------------------------------------------- |
| `snapshots`        | account calculation, evidence selection and persistence     | API, calculation/metrics, projections, evidence/manual services and writer |
| `daily_baselines`  | freeze the newest eligible complete daily or published minute baseline | service                                                        |
| `current_value`    | strict baseline-plus-delta read projection                  | API, delta projection, service and repository                              |
| `published_snapshot` | authorized latest-published snapshot reads without market I/O | portfolio and dashboard published APIs                                  |
| `net_worth`        | liability-aware aggregate evidence and projections          | API, evidence/manual services, projections, writer and repositories        |
| `snapshot_refresh` | versioned plan and coordinated market-backed/manual refresh | API, plan, executor, evidence/market/manual services and repositories      |

The domain depends on accounts, canonical cash/investment lineage, Holdings,
liabilities and selected market evidence. Read models consume only published results.
Exact files are in the [code inventory](../../map/generated/CODE-INVENTORY.md).
