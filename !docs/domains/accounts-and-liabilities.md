# Accounts and liabilities

## Scope and source of truth

`Account`, memberships, invitations, lifecycle state, and `LiabilityBalance`
are PostgreSQL-backed, Python-owned domain records. Account metadata defines
ownership/access and `Account.currency` defines intended account-level
presentation currency; it is distinct from `User.baseCurrency`, which owns
aggregate financial presentation.

## Main responsibilities

- Create, list, update, archive, restore, and authorize accessible accounts.
- Create/manage owner-governed memberships and invitations.
- Persist immutable, positive effective-at liability observations.
- Provide typed same-origin account/liability adapters to browser pages.

The primary Python entry points are `modules/accounts/api.py`,
`accounts/invitations.py`, and `modules/liabilities/api.py`. The main layers
are `accounts/{models,service,repository}.py` and
`liabilities/{models,repository,writer}.py`; browser adapters live in
`src/modules/accounts/` and `src/app/api/accounts/`.

## Boundaries and dependencies

Every financial domain references accounts and relies on backend membership
checks. Accounts do not own transactions, investment events, market evidence,
or snapshot totals. Liability observations feed valuation only through the
snapshot/current-value selection rules; they do not calculate a portfolio total
themselves.

## Invariants

- Account type is immutable after creation.
- Archive is a reversible lifecycle state, not a destructive delete.
- Owner/admin/editor/viewer behavior may be reflected in the UI, but Python is
  final authority.
- A liability balance is a positive liability amount with an explicit effective
  timestamp; the selected latest eligible observation is valuation evidence.
- Account-local primary values use account-currency evidence. Aggregate values
  remain user-base-currency evidence and must not be summed across presentation
  currencies.

## Verification and related material

- Tests: `test_accounts_*`, `test_account_access.py`,
  `test_account_membership_*`, `test_account_invitations*`,
  `test_liability_*`, and `src/modules/accounts/**/*.test.*`.
- Read [API conventions](../03-api/01-conventions.md) and the account/snapshot
  sections of [the consolidated domain model](../02-domain-model.md).
