# Cash flow

Type: domain
Status: current
Owns: transactions, categories, budgets and operational projections
Code: `transactions/`, `categories/`, `budgets/`, `operational_dashboard/`
Update when: canonical cash write, category or budget behavior changes

Transactions are canonical cash events. Categories classify them; budgets own monthly plans. The operational dashboard is a separate read-only projection and never replaces snapshot finance. Writes are Python-authorized, exact-decimal and idempotent.

Verification: [test matrix](testing.md).
