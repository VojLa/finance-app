# Identity and access

Type: domain
Status: current
Owns: credentials, Python principal and protected API authority
Code: `app/auth/`, `app/api/`, `src/lib/auth/`, `src/modules/python-api/`
Update when: identity, session bridge or authorization boundary changes

Python owns credentials, principal resolution and authorization. NextAuth owns browser session only; Next.js adapters are not a second authorization layer. See [security invariants](../../architecture/invariants/security-and-isolation.md).

Verification: [test matrix](testing.md).
