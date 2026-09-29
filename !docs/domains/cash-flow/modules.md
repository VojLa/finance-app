# Cash-flow modules

Type: module
Status: current
Owns: transaction, category, budget and operational-projection runtime layers
Code: cash-flow Python modules and matching `src/modules/` adapters
Update when: a cash-flow module, entry point or dependency changes

| Module                  | Responsibility                                        | Main layers and entry points                                  |
| ----------------------- | ----------------------------------------------------- | ------------------------------------------------------------- |
| `transactions`          | canonical cash CRUD and operational visibility        | API, service, repository, models, `operational_visibility.py` |
| `categories`            | category hierarchy and account-visible classification | API, service, repository and models                           |
| `budgets`               | monthly budget plans                                  | API, service, repository and models                           |
| `operational_dashboard` | read-only operational aggregation                     | API, service, repository and models                           |
| frontend adapters       | page contracts, clients and presentation models       | transaction, category, budget and dashboard modules           |

All writes depend on identity and account access. Transactions provide canonical
inputs to downstream valuation; budgets and categories do not alter finance lineage.
Exact files remain in the [code inventory](../../map/generated/CODE-INVENTORY.md).
