# Accounts and liabilities map

Type: domain-map
Status: current
Owns: L1 routing for accounts and liabilities
Code: account, access, invitation and liability modules/adapters
Update when: account/liability ownership, entry point or dependency changes

ID: `DOM-ACCOUNTS`
Purpose: account lifecycle, access, invitations and liability observations
Source of truth: PostgreSQL account/access/liability evidence

- Entry points: account, invitation and liability FastAPI routes.
- Modules: `accounts/`, `liabilities/`, `src/modules/accounts/`.
- Depends on: identity.
- Used by: all account-scoped finance domains.
- Tests: [domain test matrix](../../domains/accounts-and-liabilities/testing.md).
- Details: [domain README](../../domains/accounts-and-liabilities/README.md) and [modules](../../domains/accounts-and-liabilities/modules.md).
