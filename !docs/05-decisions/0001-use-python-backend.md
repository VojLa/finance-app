# 0001 Use Python Backend

## Status

Accepted.

## Decision

Use Python/FastAPI as the primary backend layer for APIs, orchestration, imports,
jobs, and provider integrations.

## Consequences

- Next.js backend logic should gradually move into Python.
- Python now provides the authenticated account, invitation, import-batch, and
  portfolio endpoints.
- Next.js routes should become thin adapters or BFF endpoints. This migration is
  incomplete: the current UI still uses legacy TypeScript routes for its main
  workflows.
- Python services need clear boundaries to avoid duplicating TypeScript business
  logic. New financial behavior belongs in Python, with the old TypeScript path
  removed only after a verified replacement exists.
