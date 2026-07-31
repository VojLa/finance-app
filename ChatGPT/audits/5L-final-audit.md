# 5L final audit — cross-boundary contract and integration audit

## Audit base SHA

`033a0886a0b2c135071c1ee56ca445a431668125`

## Audit HEAD SHA

`9f5530bf6d0949f17ee7527cb9ab74e4bca5fefa`

This is the immutable audit-evidence commit containing all tests, results,
verdict, and documentation. The following metadata-only commit records that
necessarily prior SHA in this report; the PR report records both this audit
evidence SHA and the exact final branch HEAD.

## Production files changed

None. The audit is test/docs-only.

## Route inventory

PASS. The audited inventory is exactly:

- `GET /api/v1/portfolio` — temporary legacy live reader;
- `GET /api/v1/portfolio/accounts/{account_id}/snapshot`;
- `POST /api/v1/portfolio/snapshot`;
- `POST /api/v1/dashboard/snapshot`.

The exact routes have only their intended methods and require authentication.
The two POST routes are absent from `legacy_router`; its legacy portfolio
include remains unchanged.

## Dependency-boundary result

PASS. Production dependency imports, calls, isolation ownership, model access,
and API adapter operations are guarded by AST/source audits.

## Pure-boundary result

PASS. 5L-A, 5L-D, and 5L-E import no SQLAlchemy, FastAPI, Pydantic, session,
principal, authorization, or ORM model dependency. Their pure dataclasses
remain frozen and slotted.

## Persisted-reader result

PASS. 5L-B imports only Account, AccountSnapshot, AccountSnapshotItem,
AssetListing, and Asset ORM models. It owns no begin, commit, rollback,
isolation setup, write, row lock, or advisory lock. Its read-only isolation
check remains caller-transaction validation rather than transaction ownership.

## Authorization result

PASS. Owner, admin, editor, and viewer read all exact endpoints. Foreign,
missing, and archived selectors fail without partial output; foreign and
missing share the exact `404 account_not_found` contract and responses disclose
neither selector identity nor index.

## Transaction result

PASS. SQLAlchemy event capture proves that the auth dependency transaction
precedes one financial transaction, whose first SQL is exactly
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ`. Every access and Account,
AccountSnapshot, item, listing, and asset query shares that transaction.
Dashboard opens no second transaction, and all request sessions finish idle.

## PostgreSQL coherence result

PASS. Concurrent portfolio and dashboard cases pause after the first access
query, commit a second-account metadata change elsewhere, and prove that the
original request sees the coherent older perspective while a new request sees
the committed newer perspective. No mixed response occurs.

## Read-only SQL result

PASS. Captured financial SQL contains no INSERT, UPDATE, DELETE, `FOR UPDATE`,
advisory lock, or `LOCK TABLE`. Account, membership, AccountSnapshot, and
AccountSnapshotItem counts remain unchanged across single, multi, dashboard,
and repeated requests.

## Cross-endpoint consistency result

PASS. Multi-account contributions equal their single-account views exactly.
Every aggregate financial field is the exact Decimal sum of single-account
fields. Dashboard summary values equal the corresponding portfolio aggregate,
including structural assets, counts, liabilities, cost basis, and P/L.
Account-local allocations remain 100/100 while dashboard-global allocations
are 60/40.

## Decimal serialization result

PASS. Recursive audits of all three snapshot-backed responses prove every
financial value is a JSON string that round-trips through `Decimal`. Timestamps
retain naive millisecond precision; no financial float or synthetic timezone
is present.

## Leakage result

PASS. No response contains User, membership, role, internal selected-item
lineage, persistence audit, JSONB currency breakdown, price-source, FX-source,
or credential fields. Dashboard positions additionally exclude quantity,
price, cost-basis, native-value, and snapshot-source evidence.

## Failure-contract result

PASS. Access failures retain the exact generic 404 contract. Missing or wrong
exact evidence, corrupt snapshot/item/graph data, duplicate candidates,
unsupported account types, and known SQL read failures retain the exact generic
`409 portfolio_snapshot_unavailable` contract without internal details.

## Determinism result

PASS. Repeated single, multi, and dashboard responses are byte-identical.
Account-selector permutation is byte-identical, pure input permutation is
deterministic, and equal assets in different accounts remain account-scoped.

## Unit test result

PASS. The required ten-module 5L unit/projection/API matrix completed with
`412 passed, 0 failed, 0 skipped, 0 xfailed` and 17 existing deprecation
warnings. The focused final unit audit itself completed with 76 passed.

## PostgreSQL test result

PASS. The required four-module PostgreSQL matrix completed with
`101 passed, 0 failed, 0 skipped, 0 xfailed` and two existing deprecation
warnings. The focused final PostgreSQL audit itself completed with 47 passed.
Environment-gated full-suite skips are not counted as PostgreSQL pass evidence.

## Full backend result

PASS. `uv run python scripts/check.py` completed with 2,442 passed,
496 environment-gated skipped, and 64 warnings.

## Frontend result

PASS. `npm ci`, Prisma client generation, 34 Vitest tests, lint, and
`npx tsc --noEmit` completed successfully.

## Coverage

89.47% total backend branch coverage; required floor is 70%.

## Schema/migration result

PASS. No schema, migration, Prisma, ORM, DDL, or production application file
changed.

## Known external risks

- Existing npm audit findings are external to 5L and will be reported from the
  final frontend gate.
- Existing Starlette/TestClient deprecation warnings are external to 5L.
- Historical dashboard series are not part of 5L.
- The legacy live portfolio endpoint remains as a temporary reader.

These items are not new 5L regressions.

## Final verdict

PASS

All required focused and full checks passed. Focused unit and PostgreSQL audit
runs contain no skip or xfail, production files changed is none, and no
contract mismatch, data leak, live-finance fallback, or incomplete transaction
evidence was found.
