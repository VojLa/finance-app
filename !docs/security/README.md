# Security

Type: reference
Status: current
Owns: trust-boundary and sensitive-data documentation
Code: auth, API dependencies, import boundary and shared logging
Update when: attack surface, principal, input or logging behavior changes

Python validates the internal token, resolves the principal and checks account
membership. Browser UI and adapters are not a financial authority. Imports and
provider data are untrusted.

| Concern         | Control                                       |
| --------------- | --------------------------------------------- |
| Identity        | server-only, short-lived internal tokens      |
| Authorization   | Python account-role check                     |
| Untrusted files | bounded validation and issue evidence         |
| Errors/logs     | no raw payload, secret or internal diagnostic |

## Trust boundaries

- Browser → Next.js: session cookie remains server-handled; validate public input.
- Next.js → FastAPI: use a short-lived internal token and generated transport contract.
- FastAPI → domain: resolve principal and account membership before data access.
- File/provider → parser: treat every payload as untrusted and bounded.
- Application → PostgreSQL/provider: credentials come from validated environment only.

See [security invariants](../architecture/invariants/security-and-isolation.md), the
[identity bridge](../architecture/flows/identity-bridge.md), and
[safe diagnostics](../operations/health-and-diagnostics.md).
