# 0002 - Use PostgreSQL

## Decision

Primary database is PostgreSQL.

## Why

- relational consistency
- strong support for history, indexing and transactional integrity
- good fit for finance and ledger-like workloads

## Consequences

- schema discipline matters
- migrations must stay controlled
- denormalized read data must remain secondary to canonical tables
