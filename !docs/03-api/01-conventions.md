# API Conventions

The Python API is versioned under `/api/v1`. Interactive documentation and the
OpenAPI schema are available at `/docs` and `/openapi.json` when `DOCS_ENABLED`
is true. The root endpoint (`/`) is unauthenticated and lists the advertised
service endpoints.

## Authentication

All endpoints below except liveness and readiness require
`Authorization: Bearer <internal-session-token>`. See the
[security guide](../01-architecture/04-security.md) for issuer and validation
rules. A missing/invalid token returns `401`; a service without an authentication
secret returns `503` for protected calls.

## Implemented endpoints

| Method                   | Path                                                           | Purpose                                      |
| ------------------------ | -------------------------------------------------------------- | -------------------------------------------- |
| `GET`                    | `/api/v1/health/live`                                          | Process liveness                             |
| `GET`                    | `/api/v1/health/ready`                                         | PostgreSQL readiness; `503` when unavailable |
| `GET`                    | `/api/v1/auth/me`                                              | Authenticated database identity              |
| `GET`, `POST`            | `/api/v1/accounts`                                             | List accessible accounts; create account     |
| `PATCH`                  | `/api/v1/accounts/{account_id}`                                | Update account                               |
| `POST`                   | `/api/v1/accounts/{account_id}/archive`                        | Archive account                              |
| `POST`                   | `/api/v1/accounts/{account_id}/restore`                        | Restore account                              |
| `GET`, `PATCH`, `DELETE` | `/api/v1/accounts/{account_id}/members[/{member_id}]`          | Owner-only membership management             |
| `GET`, `POST`, `DELETE`  | `/api/v1/accounts/{account_id}/invites[/{invite_id}]`          | Owner-only invitation management             |
| `POST`                   | `/api/v1/accounts/invites/accept`                              | Accept a supplied invitation token           |
| `GET`, `POST`            | `/api/v1/accounts/{account_id}/imports`                        | List/register import batches                 |
| `GET`                    | `/api/v1/accounts/{account_id}/imports/{batch_id}`             | Read a batch                                 |
| `PUT`                    | `/api/v1/accounts/{account_id}/imports/{batch_id}/file`        | Stream an octet-stream upload                |
| `POST`                   | `/api/v1/accounts/{account_id}/imports/{batch_id}/parse`       | Parse its verified file                      |
| `POST`                   | `/api/v1/accounts/{account_id}/imports/{batch_id}/normalize`   | Normalize persisted rows                     |
| `POST`                   | `/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate` | Mark repeated normalized rows as duplicates  |
| `GET`                    | `/api/v1/portfolio?account_id=…`                               | Basic holdings cost summary                  |

The legacy aliases `/health` and `/portfolio` remain without the version prefix
and are intentionally excluded from OpenAPI. New clients must use `/api/v1`.

## Responses, errors, and writes

FastAPI/Pydantic response models are the HTTP source of truth. Do not manually
duplicate them in TypeScript; planned clients should be generated from OpenAPI.
Writes use request-scoped async SQLAlchemy sessions and commit or roll back as a
unit. API errors use this stable envelope (health responses are an exception):

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "request_id": "uuid-or-null"
  }
}
```

Every response has `X-Request-ID`. Validation deliberately reports a stable
message rather than exposing Pydantic's detailed input echo. Use standard HTTP
status codes and domain error codes; never put financial payloads in logs or
errors.

`PortfolioSummary` is temporary: it represents holding cost, converts missing FX
at `1.0` while returning a warning, and serializes numeric fields as JSON
numbers. It is not a market-value, snapshot, or dashboard contract.
