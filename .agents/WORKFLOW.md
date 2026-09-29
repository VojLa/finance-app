# Finance App execution workflow

## 1. Triage

State the observable outcome, domain, user/system effect, non-goals, current source
of truth, size, risk, and cheapest useful verification. Load one project map, one
domain map, the current owner, target code, and directly related tests.

Classify impact on public API, database schema, auth/account isolation, money/FX,
imports/providers, data loss, transactions, idempotency, leases, and concurrency.
Before delegation, reduce this primary context to the exact documentation and
conversation capsule defined in `CONTEXT-POLICY.md`; workers do not repeat primary
discovery.

## 2. Choose the route

- **Direct:** obvious XS/S or no useful independent subtask.
- **Delegate:** one or more independently verifiable scopes with non-overlapping
  ownership. Use `templates/CONTEXT-MANIFEST.md` and `fork_turns: "none"`.
- **Escalate:** unresolved high-risk decision or conflicting authority. Use
  `templates/ESCALATION-PACKET.md` before implementation.

The primary agent remains acceptance owner in all routes; prefer Sol medium at task start.

## 3. Design and implementation

XS/S with a closed contract may proceed directly. M records a short layer boundary,
failure behavior, transaction behavior, and verification plan. L/XL is decomposed
into S/M steps with explicit dependencies.

Prefer a complete necessary slice: FastAPI/Pydantic → service/application →
repository/SQLAlchemy → PostgreSQL → thin Next.js adapter/UI → tests. Do not create
empty layers. Keep one independently observable behavior per step.

Non-negotiable rules:

- Python enforces financial rules, object-level authorization, and account isolation.
- Money is `Decimal` with currency and rounding; event-date FX stays distinct from
  current/snapshot FX.
- Alembic alone owns executable schema migrations; SQLAlchemy remains complete;
  archived Prisma SQL is immutable.
- Imports and providers are untrusted; secrets and raw financial inputs stay out of logs.
- Transaction, rollback, idempotency, lease, and concurrency semantics are explicit.

## 4. Progressive verification

Run the cheapest falsifying check first, then expand only for affected risk and
boundaries.

Frontend, from repository root:

```powershell
npm.cmd test -- <focused-test>
npx.cmd tsc --noEmit
npm.cmd test
npm.cmd run lint
npm.cmd run api:python:check
```

Backend, from `backend/python`:

```powershell
uv run pytest <focused-test>
uv run ruff check .
uv run ruff format --check .
uv run mypy app scripts tests
uv run pytest
uv run python scripts/check.py
```

Use the full gate only when scope/risk justifies it. API changes require OpenAPI
evidence; parser changes a regression fixture; database changes Alembic graph,
artifact, clean-upgrade, and SQLAlchemy parity evidence. Do not run `npm run build`
while `next dev` is active.

## 5. Acceptance and repair

Workers return `templates/WORKER-RESULT.md`. The primary compares their evidence to
the original criteria using `templates/ACCEPTANCE-REVIEW.md`. A blocker fix gets a
focused retest and delta review; it does not restart the whole audit unless scope or
risk changed.

Stop for a missing product choice, external/destructive authority, conflicting
source of truth, necessary scope expansion, or unresolved P0/P1 risk.

## 6. Documentation impact and completion

Apply `finance-docs`. Update only the current owner, planning decision, user guide,
generated inventory, map, or active agent workflow whose truth changed. Run
`python scripts/docs/check_docs.py` when documentation is affected.

Complete only when every criterion is accepted, checks are proportionate and pass,
the diff is in scope, deviations are disclosed, no blocker remains, and the final
handoff uses `templates/IMPLEMENTATION-OUTPUT.md`.
