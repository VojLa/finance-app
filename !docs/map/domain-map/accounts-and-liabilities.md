# Accounts and liabilities map

ID: `DOM-ACCOUNTS`
Purpose: account lifecycle, access, invitations and liability observations
Source of truth: PostgreSQL account/access/liability evidence

- Entry points: account, invitation and liability FastAPI routes.
- Modules: `accounts/`, `liabilities/`, `src/modules/accounts/`.
- Depends on: identity.
- Used by: all account-scoped finance domains.
- Tests: [domain test matrix](../../domains/accounts-and-liabilities/testing.md).
- Details: [domain README](../../domains/accounts-and-liabilities/README.md).
