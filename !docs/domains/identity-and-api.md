# Identity and API boundary

## Scope and authority

Python owns credentials, authenticated principal resolution, authorization
enforcement, and the FastAPI/Pydantic HTTP contract. NextAuth owns the browser
session only. Next.js API routes are thin same-origin adapters; they are not a
second authorization or finance layer.

## Main flow

```text
Browser session → Next.js route → short-lived internal token → FastAPI route
                                                      ↓
                                      Python auth dependency → principal
```

FastAPI exposes `/api/v1` through `backend/python/app/api/router.py`. The
public contract is exported by `backend/python/scripts/export_openapi.py` and
generates `src/generated/python-api.ts`; generated types are never hand-edited.

## Implementation boundaries

- Python: `app/auth/`, `app/api/`, `app/shared/request_context.py`, and
  `app/shared/error_handlers.py`.
- Browser: `src/lib/auth/`, `src/app/api/auth/`, and
  `src/modules/python-api/server/`.
- All account-scoped application services receive the resolved Python
  principal; identity is never accepted as caller-supplied business input.

## Contract and security rules

- A browser cookie or browser authorization header is not a FastAPI credential.
- Internal tokens are minted server-side, are short-lived, and never enter a
  client bundle or JSON response.
- Python checks authentication and account role on every protected operation.
- Public errors use stable safe envelopes. Tokens, raw bodies, database URLs,
  backend request IDs, and stack traces never cross the adapter boundary.
- OpenAPI/Pydantic response models are the HTTP source of truth. TypeScript
  validates transport shape but does not duplicate backend business validation.

## Verification and related material

- Tests: `backend/python/tests/test_auth_*.py`,
  `test_request_context.py`, `src/lib/auth.test.ts`, and
  `src/modules/python-api/**/*.test.*`.
- Read [security](../01-architecture/04-security.md) for the threat boundary,
  [API conventions](../03-api/01-conventions.md) for wire rules, and
  [decision 0007](../05-decisions/0007-python-credential-boundary.md) for the
  credential boundary.
