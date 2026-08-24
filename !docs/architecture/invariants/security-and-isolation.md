# Security and isolation invariants

Type: invariant
Status: current
Owns: `INV-AUTH-*` and `INV-INPUT-*`
Code: `app/auth/`, API dependencies, adapters and shared logging
Update when: trust boundary, authorization or sensitive-data behavior changes

- `INV-AUTH-001`: Python resolves the principal and enforces account membership for every protected operation.
- `INV-AUTH-002`: Browser code cannot select a principal or calculate a financial fallback.
- `INV-AUTH-003`: Internal service tokens are short-lived, server-only and absent from browser responses.
- `INV-INPUT-001`: Imports and provider payloads are untrusted; errors and logs do not expose raw financial payloads, tokens or internal diagnostics.
- `INV-INPUT-002`: Public errors use stable safe envelopes and do not leak secrets, stack traces or database URLs.
