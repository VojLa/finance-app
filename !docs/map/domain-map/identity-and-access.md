# Identity and access map

Type: domain-map
Status: current
Owns: L1 routing for identity and access
Code: auth, API composition and server identity adapters
Update when: identity ownership, entry point or dependency changes

ID: `DOM-IDENTITY`
Purpose: credentials, principal resolution and protected-request authority
Source of truth: Python auth and account authorization

- Entry points: `app/auth/api.py`, `app/api/router.py`, NextAuth routes.
- Modules: `app/auth/`, `src/lib/auth/`, `src/modules/python-api/server/`.
- Depends on: users and account membership.
- Used by: every protected domain.
- Rules: [security invariants](../../architecture/invariants/security-and-isolation.md).
- Tests: [domain test matrix](../../domains/identity-and-access/testing.md).
- Details: [domain README](../../domains/identity-and-access/README.md) and [modules](../../domains/identity-and-access/modules.md).
