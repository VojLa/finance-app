# Read-model modules

Type: module
Status: current
Owns: portfolio, snapshot/dashboard projection and browser presentation layers
Code: `portfolio/`, `portfolio_snapshot/`, `dashboard_snapshot/`, `src/modules/portfolio/`, snapshot dashboard UI
Update when: a projection contract, entry point or browser dependency changes

| Module                  | Responsibility                                          | Main layers and entry points                                                                |
| ----------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `portfolio`             | legacy-compatible authorized portfolio summary          | API, contracts/conversions, service and repository                                          |
| `portfolio_snapshot`    | account and multi-account snapshot projections          | APIs, authorized reader/service, aggregation, currency breakdown, projection and repository |
| `dashboard_snapshot`    | financial dashboard snapshot contract                   | API, authorized service and projection                                                      |
| `src/modules/portfolio` | snapshot/history clients, page models and UI components | client/contracts, formatting/model and holdings/allocation/currency components              |
| snapshot dashboard UI   | dashboard client, model and components                  | `src/modules/dashboard/snapshot-*`, `Snapshot*.tsx`                                         |

All readers depend on resolved identity, account access and published valuation.
They may aggregate evidence but cannot write canonical finance or invent unavailable
values. Exact files are in the [code inventory](../../map/generated/CODE-INVENTORY.md).
