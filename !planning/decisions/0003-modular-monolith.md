# 0003 - Use Modular Monolith

## Decision

The backend is designed as a modular monolith first.

## Why

- domain separation without premature distributed complexity
- easier refactoring while boundaries are still evolving
- better fit for a small team and fast iteration

## Consequences

- modules must have explicit ownership
- cross-module writes must be controlled
- not everything becomes a separate service early
