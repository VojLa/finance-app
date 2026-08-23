# Frontend and experimental Rust

## Scope and authority

Next.js pages/components present typed server-owned data and run same-origin
transport adapters. They do not own finance arithmetic, persistence, provider
calls, or account authorization. The Rust workspace is experimental and is not
called by Python in the production finance path.

## Main locations

- Presentation: `src/app/`, `src/components/`, `src/modules/`.
- Technical browser utilities: `src/lib/{auth,dates,decimal,files,logging,validation}/`.
- Generated transport: `src/generated/python-api.ts`.
- Experimental code: `backend/rust/finance_engine/`.

Top-level browser folders `analytics`, `fx`, `holdings`, `notifications`,
`pricing`, `snapshots`, `users`, and `wallet` currently contain exports or
scaffolding. They do not establish independent runtime domain authority.

## Presentation rules

- Preserve public Decimal strings through state; convert only at a leaf where a
  chart library requires a number and never feed that value back into finance.
- Same-origin routes authenticate session, allowlist public fields, call Python,
  and reduce errors safely. They do not query a database or calculate values.
- Generated OpenAPI types are regenerated, never hand-edited.
- A new visible financial metric first needs a server-owned contract and
  evidence; it cannot start as a client-side derived value.

## Verification and related material

Use focused page/module tests, then `npm.cmd test`, `npm.cmd run lint`, and
`npx.cmd tsc --noEmit` proportionately. Do not run the production build while
`next dev` is active. Rust changes use `cargo test` and require an explicit
boundary/parity design before becoming production authority. Read
[coding standards](../04-development/03-coding-standards.md) and
[the TypeScript boundary policy](../../scripts/typescript-boundary-policy.json).
