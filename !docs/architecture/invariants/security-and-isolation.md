# Security and isolation invariants

Type: invariant
Status: current
Owns: `INV-AUTH-*` and `INV-INPUT-*`
Code: `app/auth/`, API dependencies, adapters and shared logging
Update when: trust boundary, authorization or sensitive-data behavior changes

| ID              | Exact rule                                                                                                                 | Primary enforcement                                 | Representative evidence                           |
| --------------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------- |
| `INV-AUTH-001`  | Python resolves the principal and enforces account membership for every protected operation.                               | auth dependency plus account access service         | auth API, account-access and portfolio-auth tests |
| `INV-AUTH-002`  | Browser code cannot select a principal or calculate a financial fallback.                                                  | server adapters and TypeScript boundary policy      | boundary, cutover and clean-main frontend tests   |
| `INV-AUTH-003`  | Internal service tokens are short-lived, server-only and absent from browser responses.                                    | internal-token issuer and server-only modules       | token and internal-token adapter tests            |
| `INV-INPUT-001` | Imports and provider payloads are untrusted; errors and logs omit raw financial payloads, tokens and internal diagnostics. | upload/provider validation and shared logging       | upload-security, parser and request-context tests |
| `INV-INPUT-002` | Public errors use stable safe envelopes and do not leak secrets, stack traces or database URLs.                            | shared error handlers and adapter error translation | error, auth-route and transport tests             |
