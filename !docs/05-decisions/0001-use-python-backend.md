# 0001 Use Python Backend

## Status

Accepted.

## Decision

Use Python/FastAPI as the primary backend layer for APIs, orchestration, imports, jobs, and provider integrations.

## Consequences

- Next.js backend logic should gradually move into Python.
- Next.js routes should become thin adapters or BFF endpoints.
- Python services need clear boundaries to avoid duplicating TypeScript business logic.
