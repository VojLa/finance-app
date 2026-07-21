# 0002 Use Modular Monolith

## Status

Accepted.

## Decision

Use a modular monolith structure before splitting into separate services.

## Consequences

- Domains should be separated by modules.
- Shared database access must stay controlled: `db/` provides infrastructure,
  while module repositories make domain queries explicit.
- The implemented modules are accounts, imports, and the basic portfolio read
  model. Schema-only domains must not be treated as implemented services.
- Rust calculation engines can be introduced only behind explicit Python-owned
  interfaces; the current Rust crate is a prototype, not a running dependency.
