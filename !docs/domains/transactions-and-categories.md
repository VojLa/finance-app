# Transactions and categories

## Scope and source of truth

Transactions are canonical, account-scoped cash events stored in PostgreSQL.
Categories are default or user-owned hierarchy records that classify
transactions. The browser only submits validated command payloads and renders
typed responses; it never owns transaction arithmetic or authorization.

## Main responsibilities

- List filtered, paginated accessible transactions.
- Create, replace, and tombstone manual cash transactions through idempotent
  commands.
- Maintain default categories and user custom category hierarchy.
- Expose transaction visibility to budgets and operational dashboard projections.

Python entry points are `modules/transactions/api.py` and
`modules/categories/api.py`; their services/repositories own writes and reads.
Next.js adapters are `src/app/api/transactions/` and
`src/app/api/categories/`, with browser contracts in matching `src/modules/`.

## Write semantics

Amounts arrive as positive exact decimal input. Python stores expense as a
negative canonical amount and income as positive. A new successful command
creates one canonical revision; exact idempotency replay succeeds, while reuse
of a key with different payload conflicts. Pair/split transaction editing stays
unsupported until it has a dedicated compound operation.

## Invariants

- Money is `Decimal`, serialized as a fixed-scale string at the public boundary.
- Account access is checked in Python for every list and write.
- Categories cannot create cycles or attach to inaccessible parents.
- Default categories are immutable; custom-category deletion follows the
  database-owned reference/cascade contract.
- Operational reporting reads persisted transaction evidence and cannot become a
  financial snapshot fallback.

## Verification and related material

- Tests: `test_transactions_categories*`,
  `test_operational_transaction_visibility*`, `test_categories_*`, and
  TypeScript transaction/category client tests.
- Read [API conventions](../03-api/01-conventions.md) and
  [coding standards](../04-development/03-coding-standards.md).
