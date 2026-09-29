# Review: [step/diff]

Review only the supplied contract, diff, directly coupled contracts, and verification
evidence. Do not implement fixes.

## Priority

1. Data loss/corruption, money, security, auth/account isolation.
2. Behavior, API/schema compatibility, transactions, rollback, idempotency,
   leases, and concurrency.
3. Missing, misleading, or non-falsifying tests.
4. Module boundaries, duplication, recovery, and maintainability.
5. Style only when it has practical impact.

Confirm that Python remains finance/auth authority; money uses `Decimal`, currency,
rounding, and correct FX time; Alembic alone owns migrations; SQLAlchemy parity and
OpenAPI are preserved; secrets/raw financial inputs stay out of logs.

## Findings

For each finding provide P0–P3, file/line, evidence, impact, violated criterion or
invariant, and the smallest repair. Do not report speculative or purely stylistic
findings.

If no substantive finding exists, say so and list residual risk or verification not
performed. Return read-only evidence in `WORKER-RESULT.md` format; the primary owns
acceptance.
