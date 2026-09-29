# Identity and access

Type: domain
Status: current
Owns: credentials, Python principal and protected API authority
Code: `app/auth/`, `app/api/`, `src/lib/auth/`, `src/modules/python-api/`
Update when: identity, session bridge or authorization boundary changes

Python owns credentials, principal resolution and authorization. NextAuth owns browser
session only; Next.js adapters are not a second authorization layer.

## Capabilities and boundaries

- register, authenticate and change a password through Python-owned credentials;
- convert a server-side browser session into a short-lived internal token;
- resolve a principal for protected FastAPI operations;
- change the authenticated user's aggregate base currency through an exact,
  transactional mutation that invalidates portfolio history;
- keep account membership authorization in the owning account/domain service;
- expose liveness/readiness without making health routes a business authority.

It does not own account roles, financial data or browser-selected user identity.
`PUT /api/v1/auth/me/base-currency` accepts only an uppercase three-letter ASCII
code. A real change takes the snapshot-series publication lock before the User
row lock and commits the User update, scope-dirty history state, schedule and
rebuild job together. Repeating the persisted value is a complete no-op.

## Navigation

- [Module and layer map](modules.md)
- [Identity bridge flow](../../architecture/flows/identity-bridge.md)
- [Security invariants](../../architecture/invariants/security-and-isolation.md)
- [API conventions](../../api/conventions.md)
- [Test matrix](testing.md)
