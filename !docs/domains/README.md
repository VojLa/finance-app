# Domains

Type: reference
Status: current
Owns: routing to implemented business and platform ownership
Code: `backend/python/app/modules/`, `src/modules/`
Update when: a domain is added, removed or changes source of truth

| Domain                                                         | Owns                                |
| -------------------------------------------------------------- | ----------------------------------- |
| [Identity and access](identity-and-access/README.md)           | principal and authorization         |
| [Accounts and liabilities](accounts-and-liabilities/README.md) | accounts and liability evidence     |
| [Cash flow](cash-flow/README.md)                               | transactions, categories, budgets   |
| [Imports and jobs](imports-and-jobs/README.md)                 | untrusted file workflow             |
| [Investments and holdings](investments-and-holdings/README.md) | canonical investment history        |
| [Market data and FX](market-data-and-fx/README.md)             | provider and price evidence         |
| [Valuation](valuation/README.md)                               | snapshots and current value         |
| [Read models](read-models/README.md)                           | portfolio and dashboard             |
| [Portfolio history](portfolio-history/README.md)               | renewable published snapshot series |
| [Platform](platform/README.md)                                 | persistence and frontend boundaries |

The generated [module inventory](../map/generated/MODULE-INVENTORY.md) provides the exhaustive module list. Legacy summaries remain migration sources only.
