# 0002 Use Modular Monolith

## Status

Accepted.

## Decision

Use a modular monolith structure before splitting into separate services.

## Consequences

- Domains should be separated by modules.
- Shared database access must stay controlled.
- Rust calculation engines can be introduced behind explicit interfaces.

