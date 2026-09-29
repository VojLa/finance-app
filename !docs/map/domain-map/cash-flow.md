# Cash-flow map

Type: domain-map
Status: current
Owns: L1 routing for cash flow
Code: transaction, category, budget and operational-dashboard modules/adapters
Update when: cash-flow ownership, entry point or dependency changes

ID: `DOM-CASH`
Purpose: cash transactions, categories, budgets and operational reporting
Source of truth: canonical transactions, category hierarchy and budget plans

- Entry points: transactions, categories, budgets and operational-dashboard APIs.
- Modules: `transactions/`, `categories/`, `budgets/`, `operational_dashboard/`.
- Depends on: identity and accounts.
- Used by: operational dashboard and valuation inputs where applicable.
- Tests: [domain test matrix](../../domains/cash-flow/testing.md).
- Details: [domain README](../../domains/cash-flow/README.md) and [modules](../../domains/cash-flow/modules.md).
