# API conventions

Type: reference
Status: current
Owns: human-readable HTTP and adapter conventions
Code: FastAPI Pydantic models, API router and same-origin adapters
Update when: auth, error, serialization or API versioning changes

FastAPI `/api/v1` and its Pydantic models are the HTTP contract authority.
OpenAPI generates TypeScript transport types; generated files are never edited.
Next.js routes provide a narrow server-only bridge, but not finance behavior.

- Protected operations resolve the Python principal; callers cannot select it.
- Public errors use `{ error: { code, message, request_id } }`.
- Decimal financial values are exact strings, not JSON numbers.
- Raw bodies, cookies and authorization headers are not logged.

Endpoint and schema facts are in [API inventory](../map/generated/API-INVENTORY.md).
