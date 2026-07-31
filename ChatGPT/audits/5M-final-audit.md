# 5M final audit — snapshot application cutover

## Audit base SHA

`64d1e151baf90e160b45d86e8d415811f5dc42f1`

## Audit final HEAD SHA

The exact immutable final HEAD is recorded in the draft PR body after the audit
commit is created. A file contained by a Git commit cannot embed that commit's
own object ID without changing the object ID.

## Production files changed

None.

The audit diff contains only frontend tests, Python tests and test support, this
report, and the explicitly permitted documentation updates.

## Route inventory

Exactly two browser workflow routes exist:

- `POST /api/snapshot-workflow/portfolio`;
- `POST /api/snapshot-workflow/dashboard`.

Both are POST-only, accept no request object or body, call
`getServerSession(authOptions)` once, reject a missing or blank `session.user.id`,
delegate once, and return `Cache-Control: no-store`. No GET variant exists.

## Browser boundary

Portfolio current finance calls only the relative Next route
`/api/snapshot-workflow/portfolio`. Dashboard finance calls only
`/api/snapshot-workflow/dashboard`. Client boundaries contain no FastAPI
snapshot paths, backend URL, internal secret, `jose`, token issuer, or server
configuration import. The browser never calls FastAPI directly.

## NextAuth boundary

Missing session, missing `session.user`, and blank user ID return the stable
`401 authentication_required` envelope before workflow execution. Valid
sessions with and without email preserve the exact server-owned user ID; email
remains optional. Browser headers and body fields cannot replace the subject or
provide selectors.

## Cross-runtime token verification

The TypeScript `issueInternalToken()` output was sent to a Python test helper
through stdin. The helper used the production `InternalTokenVerifier` and
accepted the HS256 signature, issuer, audience, subject, issued-at, expiry,
unique token ID, and optional email. Wrong secret, issuer, audience, expiry,
future issuance, and malformed tokens were rejected with a generic safe result.
Tokens were never passed as command-line arguments or echoed in stdout/stderr.

## Token-per-request evidence

Both ready in-process workflows issued two distinct bearer tokens with two
distinct `jti` claims: one immediately before refresh and one immediately
before the exact 5L read. No token was cached or reused.

## OpenAPI generation evidence

FastAPI OpenAPI remains the only source of the refresh, exact manifest,
portfolio, and dashboard DTOs. `snapshot-workflow-contract.ts` aliases the four
generated schemas, the generated file retains its do-not-edit header, and
`npm run api:python:check` passed without changing the working tree.

## Portfolio ready flow

The in-process audit connected:

```text
requestPortfolioPageState
  -> Next portfolio route
  -> verified session
  -> real server workflow/client
  -> mocked FastAPI refresh
  -> exact portfolio read
  -> ready browser state
  -> buildPortfolioPageModel
```

Refresh was first and portfolio read second. The JSON manifest matched
byte-for-byte, response identity matched the selector, safe refresh metadata
excluded accounts, Decimal strings survived transport, and the page model
retained the server summary/account objects. Local account selection made no
request.

## Portfolio empty flow

An empty refresh produced `status: "empty"` with no `data`, manifest, or
selector. Exactly one FastAPI refresh request occurred and no portfolio,
legacy, rates, discovery, or latest lookup followed.

## Portfolio error flow

Transport and contract failures produced stable safe page errors with one
request and no retry. Raw exception text, backend URL, token, cookie, or stack
trace did not enter public state.

## Portfolio history isolation

`GET /api/portfolio/history` remains chart/range/tooltip-only. Current cards,
positions, allocation, account selection, and output currency are sourced from
the ready snapshot response. No latest history point can become current
fallback data.

## Dashboard ready flow

The dashboard in-process audit connected the browser client, Next route,
verified session, real workflow/client, refresh, dashboard exact read, ready
state, and `buildSnapshotDashboardModel`. The exact manifest was unchanged,
common identity and account set matched, Decimal summary/account/allocation
values survived transport, and server top-position ordering was retained.

## Dashboard empty flow

An empty refresh made one FastAPI request and returned `status: "empty"` with
no `data`, manifest, or selector. No dashboard 5L read occurred. The independent
operational request could still return its narrow successful state.

## Dashboard error flow

Snapshot failure remained a safe financial error while successful operational
data stayed available. Operational failure cannot remove a successful snapshot
model. Neither branch is a financial fallback for the other.

## Operational isolation

The operational adapter physically creates a new model containing only
current-month income, expenses and net cash flow, budget, expense categories,
monthly trends, and recent transactions. Legacy net worth, portfolio value,
cash, liabilities, account balances, `totalCzk`, and balance breakdowns are
discarded. Snapshot net deposits and P/L are never used as monthly cash flow.

## Legacy financial fallback audit

Portfolio current presentation contains no legacy current API, rates refresh,
legacy recalculation, Prisma, price provider, FX service, latest history
fallback, or history-owned current data. Dashboard snapshot production modules
contain none of the forbidden legacy financial fields. Empty and error states
do not synthesize zero finance.

## Decimal preservation

The audit preserved these strings byte-for-byte through workflow state and page
models:

```text
0
-0.000001
123456789012.123456
999999999999.999999
0.3333
100.0000
```

Card/table models use the original strings, and chart tooltips retain exact
allocation strings.

## Financial-calculation audit

Snapshot clients, models, cards, and tables contain no `Number`, `parseFloat`,
`parseInt`, `Math.round`, `toFixed`, or `reduce` financial calculation. Exactly
one documented presentation-only conversion exists in the portfolio Recharts
leaf and one in the dashboard Recharts leaf. Neither is used for cards, tables,
exact tooltips, sorting, decisions, or further finance.

## Request-count audit

- initial portfolio browser workflow: 1;
- ready portfolio FastAPI requests: 2;
- empty portfolio FastAPI requests: 1;
- portfolio account selector requests: 0;
- initial dashboard financial browser workflow: 1;
- ready dashboard FastAPI requests: 2;
- empty dashboard FastAPI requests: 1;
- initial operational dashboard request: 1;
- financial refresh leaves the operational count unchanged.

## Retry/cache audit

No automatic retry, background refresh, timestamp cache busting, or response
cache was found. Browser and server requests use `no-store`. Refresh and read
use fresh tokens.

## Leakage audit

Public workflow/page-state evidence contains no internal bearer token, secret,
NextAuth JWT, browser cookie, password hash, email, membership role, refresh
mode, write disposition, selected item IDs, price/exchange-rate evidence,
writer command, backend URL, or request ID. Safe refresh summaries contain no
`accounts`, `accountId`, or `snapshotId`. Account/snapshot identity inside the
approved 5L data remains public by contract.

## Backend unit result

`uv run python scripts/check.py` passed:

- 2,463 passed;
- 526 environment-gated integration tests skipped, reported as skipped rather
  than passed;
- 0 failed;
- coverage 89.46% against a 70% requirement.

Ruff lint/format and mypy also passed independently.

## PostgreSQL result

The required focused matrix ran against a dedicated real PostgreSQL 16.10
database, `finance_app_5m_final_audit`, not SQLite or a mock:

- 104 passed;
- 0 failed;
- 0 skipped;
- 0 xfailed.

## Frontend focused result

The four final-audit files plus workflow route, portfolio/dashboard page,
client, workflow, and token tests produced:

- 10 test files passed;
- 137 tests passed;
- 0 failed;
- 0 skipped;
- 0 xfailed.

## Frontend full result

`npm test` passed 25 test files and 229 tests with 0 failures.

## TypeScript result

`npx tsc --noEmit` passed.

## Lint result

`npm run lint` passed without warnings or errors.

## OpenAPI drift result

`npm run api:python:check` passed and left the working tree unchanged.

## Schema result

`npm run db:generate` and `npm run db:validate` passed. No schema, migration,
DDL, ORM, or generated-contract file changed.

## Formatting baseline

Changed-file Prettier and `git diff --check` passed. Repository-wide
`npm run format:check` is not passed: it still reports only the same 16
pre-existing Markdown files, all verified byte-identical to the audit base:

- `!docs/01-architecture/02-modules.md`;
- `!docs/02-imports/01-overview.md`;
- `!docs/02-imports/02-parser-contract.md`;
- `!docs/02-imports/03-supported-sources.md`;
- `ChatGPT/steps/5F-B1.md`;
- `ChatGPT/steps/5F-B2.md`;
- `ChatGPT/steps/5G-B.md`;
- `ChatGPT/steps/5G-B1.md`;
- `ChatGPT/steps/5G-B2.md`;
- `ChatGPT/steps/5G-B3.md`;
- `ChatGPT/steps/5H.md`;
- `ChatGPT/steps/5I.md`;
- `ChatGPT/steps/5K-final-audit.md`;
- `ChatGPT/templates/EPIC.md`;
- `ChatGPT/templates/IMPLEMENTATION-OUTPUT.md`;
- `ChatGPT/WORKFLOW.md`.

## GitHub Actions coverage

`backend-python.yml` covers PR changes under `backend/python/**`.
`database-schema.yml` covers database/schema paths and
`backend/python/tests/**`; this audit PR therefore triggers both because it adds
Python tests. No workflow covers a frontend-only `src/**` PR. That gap is a
visible process/release risk; local execution is not presented as remote CI,
and this audit does not add a workflow.

## npm audit findings

`npm ci` audited 680 packages and reported 21 existing vulnerabilities:
1 low, 1 moderate, 18 high, and 1 critical. No dependency changed in this
audit-only PR.

## Known residual legacy routes

The legacy current portfolio/dashboard compatibility routes remain registered.
Portfolio history remains a legacy chart-only surface. Dashboard operational
widgets temporarily retain the legacy dashboard read. Removing or narrowing
these surfaces is outside 5M final audit.

## Final verdict

**PASS**

The snapshot application cutover is complete: portfolio current finance and
dashboard financial presentation are snapshot-backed end to end, empty and
error branches fail closed, legacy finance is not a fallback, and the frontend
creates no competing financial authority.
