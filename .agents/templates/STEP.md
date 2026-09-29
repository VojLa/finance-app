# Step [ID]: [one observable capability]

## Contract

- Epic/milestone:
- Outcome:
- Size/score and risk:
- Acceptance owner:
- Recommended worker model/effort:
- Current source of truth:

## Context

- Project/domain map:
- Current domain owner:
- Decisions/invariants:
- Target code and directly related tests:

## Scope

- One behavior:
- Exact write scope:
- Non-goals:
- Dependencies and file ownership:

## Required behavior

1. Happy path:
2. Errors and boundary cases:
3. Auth/account isolation:
4. Transaction/rollback/idempotency/concurrency:
5. Money/currency/rounding/FX:

## Data and contracts

Describe API/OpenAPI compatibility and persistence impact. SQLAlchemy is the
complete runtime mapping; Alembic is the sole executable migration owner;
`prisma/migrations/` is immutable historical evidence. State why schema is unchanged
or name the Alembic revision, artifact, parity, rollout, and recovery evidence.

## Acceptance criteria

- [ ] Binary independently verifiable condition.
- [ ] Negative or failure behavior is proven when relevant.
- [ ] Diff stays in scope and generated files come from generators.
- [ ] Documentation impact is recorded.

## Verification

- Cheapest falsifying test:
- Boundary/integration check:
- Static/full gate only when justified:

For a delegated step, convert this contract into `CONTEXT-MANIFEST.md`. Final
initiative output uses `IMPLEMENTATION-OUTPUT.md`.
