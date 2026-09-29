# Cash flow

Type: domain
Status: current
Owns: transactions, categories, budgets and operational projections
Code: `transactions/`, `categories/`, `budgets/`, `operational_dashboard/`
Update when: canonical cash write, category or budget behavior changes

Transactions are canonical cash events. Categories classify them; budgets own monthly plans. The operational dashboard is a separate read-only projection and never replaces snapshot finance. Writes are Python-authorized, exact-decimal and idempotent.

## Capabilities and boundaries

- list, create, update and delete canonical cash transactions;
- maintain account-visible category hierarchy and monthly budgets;
- project operational income, expense and budget status;
- expose narrow Next.js adapters for the corresponding UI pages.

The operational dashboard is not the snapshot-backed financial dashboard and cannot
be used as canonical history or valuation evidence.

## Navigation

- [Module and layer map](modules.md)
- [Canonical write flow](../../architecture/flows/canonical-write.md)
- [Canonical and money invariants](../../architecture/invariants/README.md)
- [Test matrix](testing.md)
