# 0005 FastAPI OpenAPI is the HTTP contract source

## Status

Accepted; client generation is not implemented yet.

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
