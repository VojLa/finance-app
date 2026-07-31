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
duplicate them in TypeScript. `npm run api:python:generate` exports OpenAPI
directly from `create_app(...)` without database or lifespan work and generates
`src/generated/python-api.ts`; `npm run api:python:check` detects drift without
changing the working tree.
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

## Next.js snapshot workflow routes

Next.js exposes two server-owned browser integration routes:

| Method | Path                               | Purpose                              |
| ------ | ---------------------------------- | ------------------------------------ |
| `POST` | `/api/snapshot-workflow/portfolio` | Refresh and exact portfolio snapshot |
| `POST` | `/api/snapshot-workflow/dashboard` | Refresh and exact dashboard snapshot |

They accept no body or selectors and require a valid NextAuth session. A
non-empty refresh manifest is carried unchanged to exactly one 5L endpoint and
returns discriminated `status: "ready"` with a safe refresh summary and the
unchanged generated 5L response. An empty refresh returns `status: "empty"`
with only the safe summary and calls no 5L endpoint. Neither response separately
exposes refresh `accounts`, `accountId`, or `snapshotId`.

All responses use `Cache-Control: no-store`. Adapter errors use a Next-owned
`{error: {code, message}}` envelope. Authentication failure is 401,
configuration failure is 503, and transport or contract failure is 502. Safe
Python 404/409 errors may retain status/code/message; Python request IDs, raw
bodies, headers, tokens, and tracebacks never cross the boundary.

## Portfolio page integration

The portfolio page uses `POST /api/snapshot-workflow/portfolio` exactly once on
initial load and once per explicit refresh action. The request has no body,
selector, query parameter, manifest, account ID, snapshot ID, timestamp,
currency, or calculation version. The page no longer calls the legacy current
`GET /api/portfolio`, rates refresh, or legacy snapshot recalculation routes.

`status: "empty"` is rendered as a successful no-account state and makes no
follow-up request. `status: "ready"` supplies current cards and positions
directly from the generated snapshot response. The aggregate selector uses the
server aggregate summary; account selection uses the corresponding account
summary and positions from the same loaded response without another request.
There is no frontend financial aggregation, FX, pricing, allocation
calculation, latest-snapshot lookup, or fallback.

The portfolio response provides account-local position allocation but no
global multi-account position allocation or return percentage. The page hides
those aggregate presentation elements rather than deriving them. Decimal
strings remain unchanged in page state; only the account-local allocation
chart converts its server percentage at the Recharts leaf.

`GET /api/portfolio/history` remains temporarily available for the historical
line and range selector. History never supplies current cards, positions,
allocation, account options, or currency and its latest point does not override
the current snapshot response. The legacy route implementation remains
registered.

## Dashboard page integration

The dashboard page uses `POST /api/snapshot-workflow/dashboard` exactly once on
initial load and once per explicit financial refresh. Its bodyless no-store
response is the only authority for financial summary values, account and
position counts, financial account cards, asset-type allocation, and top
positions. Decimal strings remain unchanged; allocation is server-calculated
and top positions retain server ranking.

In parallel, `GET /api/dashboard` temporarily supplies only operational
current-month income, expenses and net cash flow, budget, expense categories,
monthly trends, and recent transactions. The page adapter discards the legacy
financial summary and account balances. This response is never a financial
fallback and cannot change snapshot data.

Snapshot and operational states and errors are separate. A snapshot `empty`
result renders an explicit no-account financial state while operational widgets
may remain available. Snapshot failure does not reveal legacy financial data,
and operational failure does not remove a successful snapshot section. The
financial refresh calls only the snapshot workflow and does not retry.

The portfolio page remains snapshot-backed. The unchanged legacy dashboard
route remains registered only for these temporary operational widgets. The next
step is the 5M final audit.
