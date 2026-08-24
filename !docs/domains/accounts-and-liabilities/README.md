# Accounts and liabilities

Type: domain
Status: current
Owns: accounts, membership, invitations, lifecycle and liability evidence
Code: `modules/accounts/`, `modules/liabilities/`, `src/modules/accounts/`
Update when: account authority, lifecycle or liability evidence changes

`Account`, membership, invitation and `LiabilityBalance` records are PostgreSQL evidence owned by Python. `Account.currency` controls account presentation; `User.baseCurrency` controls aggregates. Archive is reversible, not deletion.

Verification: [test matrix](testing.md).
