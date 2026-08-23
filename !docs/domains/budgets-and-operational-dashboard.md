# Budgets and operational dashboard

## Scope and source of truth

Budgets own exact monthly plan data. The operational dashboard is a read-only
projection of persisted transaction, category, and budget evidence for current
cash-flow operations. It is intentionally separate from snapshot-backed
portfolio/dashboard finance.

## Responsibilities and boundaries

- Replace one accessible user's monthly budget plan atomically.
- Validate category and account scope and optionally read rollover from the
  immediately preceding persisted plan.
- Return current-month income, expenses, net cash flow, category breakdown,
  trends, recent transactions, and budget progress.

Python modules are `budgets/` and `operational_dashboard/`, each with an
`api.py` adapter and service/repository layers. Browser integration is
`src/app/api/budget/`, `src/app/api/dashboard/`, `src/modules/budgets/`, and
`src/modules/dashboard/`.

Operational widgets may render beside financial snapshot widgets, but each has
independent fetch/state/error behavior. This module does not request providers,
calculate market value, read a legacy financial fallback, or write canonical
financial events.

## Invariants and verification

- Decimal values remain exact string contracts at the browser boundary.
- Budget writes serialize by principal and month and replace the selected plan
  plus children as one operation.
- Account/category access is validated by Python.
- An operational failure never hides a valid financial snapshot and a successful
  operational response never changes financial-snapshot meaning.

Tests include `test_budgets_operational_dashboard*`,
`test_operational_transaction_visibility*`, budget client tests, and
`src/modules/dashboard/operational-dashboard-model.test.ts`. See
[technical overview](../01-architecture/01-technical-overview.md).
