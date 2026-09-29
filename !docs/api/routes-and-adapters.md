# API routes and browser adapters

Type: reference
Status: current
Owns: mapping between transport groups, domain owners and Next.js adapters
Code: FastAPI router, domain APIs and `src/app/api/`
Update when: a route group changes owner or a same-origin adapter is added/removed

| Domain owner         | FastAPI operation groups                                    | Next.js adapter surface                                                 |
| -------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------- |
| Identity/access      | auth, authenticated base-currency mutation and health       | `/api/auth/*`, `/api/health`                                            |
| Accounts/liabilities | accounts, invitations, membership and liability balances    | `/api/accounts/*`                                                       |
| Cash flow            | transactions, categories, budgets and operational dashboard | `/api/transactions`, `/api/categories`, `/api/budget`, `/api/dashboard` |
| Imports/jobs         | import stages, batches, jobs and retry                      | `/api/import`, `/api/import/jobs/*`                                     |
| Investments/Holdings | manual investment events and Holding rebuild                | `/api/portfolio/transactions` plus server module adapters               |
| Valuation            | snapshots, current value, published snapshot reads, net worth and snapshot refresh | `/api/snapshot-workflow/*`                              |
| Read models          | portfolio and dashboard snapshot reads                      | portfolio/dashboard server adapters                                     |
| Portfolio history    | published history read                                      | `/api/portfolio/history`                                                |

`GET /api/v1/portfolio/history` reads only the current immutable history
generation. Its `range` is one of `1D`, `1W`, `1M`, `3M`, `6M`, `1Y`, `5Y`,
`10Y` or `ALL`, anchored to the published `coveredThrough`. A published response
reports the requested preferred resolution, the actual persisted resolutions and
half-open coverage segments; every point reports its actual `resolutionMinutes`.
An optional `accountId` selects the already persisted points for one current,
authorized account in that same frozen generation; omitting it returns the
aggregate. A missing, foreign, inactive, or scope-mismatched account fails closed.
Only complete preferred or coarser persisted coverage can be mixed. Missing or
malformed coverage fails closed with `409` and is never filled by interpolation,
finer data or repeated closes. The response has at most 480 ordered,
timestamp-unique points. The public state is `ready`, `rebuilding`, `failed` or
`empty`; `rebuilding` and `failed` can retain the last safe generation only when its
scope still matches. Scope-dirty rebuilds never expose generation metadata,
coverage or points.

FastAPI composes the versioned `/api/v1` contract. Next.js route handlers are
server-only transport bridges for browser session, request validation and response
translation; they cannot implement alternate finance calculations or authorization.
Exact methods, paths and operation IDs are generated in the
[API inventory](../map/generated/API-INVENTORY.md).

`POST /api/v1/portfolio/published` and `POST /api/v1/dashboard/published`
select the newest complete authorized baseline and read only its persisted
snapshot identities. They do not acquire prices/FX or invoke a refresh; browser
navigation uses these routes while `/current` remains an explicit live-value
boundary.

`PUT /api/v1/auth/me/base-currency` owns the public User aggregate-currency
mutation. Its body and response use `baseCurrency`; input is an exact uppercase
three-letter ASCII code and the response is `no-store`. A successful real change
hides the old history publication behind scope-dirty state until its direct-FX,
source-policy-consistent replacement is published. It never relabels old current
or daily-baseline aggregates.
