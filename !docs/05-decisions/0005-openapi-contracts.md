# 0005 FastAPI OpenAPI is the HTTP contract source

## Status

Accepted; deterministic TypeScript client contract generation is implemented.

## Decision

FastAPI response and request models define the Python HTTP contract. FastAPI
generates OpenAPI at `/openapi.json` when `DOCS_ENABLED=true`; TypeScript types
and clients should be generated from that document rather than maintained as
parallel handwritten DTOs.

## Consequences

- HTTP behavior is versioned below `/api/v1`.
- A contract change must update the Pydantic model, endpoint tests, and this
  documentation where it changes integration behavior.
- Breaking changes require an explicit versioning or compatibility decision.
- The live OpenAPI document is the detailed endpoint reference; the API guide
  in this directory records conventions and operationally important limits.
- Existing Next.js route contracts remain legacy compatibility surfaces until
  their Python replacements are connected and verified.

## Implemented generation boundary

`backend/python/scripts/export_openapi.py` constructs the FastAPI application
with test-safe settings and exports deterministic JSON without starting
lifespan or connecting to PostgreSQL. The cross-platform Node generator invokes
`openapi-typescript` and writes the tracked
`src/generated/python-api.ts` with an explicit generated-file header.

`npm run api:python:check` repeats export and generation in a temporary
directory, compares content in Node, returns nonzero on drift, and never writes
the tracked file. The 5M-B server adapter imports its refresh, selector,
portfolio, and dashboard HTTP DTOs only from this generated contract.

## Final cutover audit evidence

The 5M final audit reruns the deterministic drift check and verifies the full
chain from FastAPI OpenAPI through `src/generated/python-api.ts` to the
Next-owned discriminated workflow contract. Refresh, exact-manifest,
portfolio, and dashboard transport DTOs remain aliases of generated schemas;
no handwritten Python financial response type was introduced.

The audit also exercises the generated contracts through the real Next
workflow services for ready and empty portfolio and dashboard flows. The
tracked generated file remains unchanged, and the audit introduces no
production contract, endpoint, dependency, schema, or migration change.
