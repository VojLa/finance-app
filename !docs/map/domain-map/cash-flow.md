# Cash-flow map

ID: `DOM-CASH`
Purpose: cash transactions, categories, budgets and operational reporting
Source of truth: canonical transactions, category hierarchy and budget plans

- Entry points: transactions, categories, budgets and operational-dashboard APIs.
- Modules: `transactions/`, `categories/`, `budgets/`, `operational_dashboard/`.
- Depends on: identity and accounts.
- Used by: operational dashboard and valuation inputs where applicable.
- Tests: [domain test matrix](../../domains/cash-flow/testing.md).
- Details: [domain README](../../domains/cash-flow/README.md).
