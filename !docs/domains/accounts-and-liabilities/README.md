# Accounts and liabilities

Type: domain
Status: current
Owns: accounts, membership, invitations, lifecycle and liability evidence
Code: `modules/accounts/`, `modules/liabilities/`, `src/modules/accounts/`
Update when: account authority, lifecycle or liability evidence changes

`Account`, membership, invitation and `LiabilityBalance` records are PostgreSQL evidence owned by Python. `Account.currency` controls account presentation; `User.baseCurrency` controls aggregates. Archive is reversible, not deletion.

## Capabilities and boundaries

- create, read and update accounts, membership and invitations;
- archive and restore account access without deleting history;
- authorize account-scoped operations by membership role;
- record dated liability balances as explicit evidence.

Credit cards are ledger-backed signed accounts for valuation: their canonical
transactions produce the balance, and a negative balance is debt. A credit
limit is not valuation evidence. Loans and mortgages continue to require
explicit dated liability-balance evidence.

Accepted membership and active-account scope changes are serialized with the
snapshot-series publication fence. Account create, invite acceptance, accepted
member removal, archive/restore and real currency changes dirty and enqueue the
affected user histories in the same transaction; role, invite lifecycle,
same-currency and presentation-only changes do not.

The domain does not calculate portfolio value or net worth. Those consumers read
account and liability evidence through valuation/read-model services.

## Navigation

- [Module and layer map](modules.md)
- [Security invariants](../../architecture/invariants/security-and-isolation.md)
- [Money and currency invariants](../../architecture/invariants/money-and-currency.md)
- [Data ownership](../../data/ownership.md)
- [Test matrix](testing.md)
