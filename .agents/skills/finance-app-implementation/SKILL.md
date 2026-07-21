---
name: finance-app-implementation
description: Implement or verify an approved finance-app roadmap step in the local repository. Use for scoped backend, frontend, database, import, auth, portfolio, migration, refactor, or bug-fix work that requires repository inspection, incremental implementation, tests, repair loops, diff audit, and a final local report. Do not use to invent product scope or make unapproved public-contract, migration-ownership, security-boundary, or financial-invariant decisions.
---

# Finance App Implementation

## Required input

Obtain or identify:

- an approved implementation specification or an unambiguous small-task description
- the expected base branch and implementation branch
- the roadmap or issue identifier when applicable
- any accepted review findings when running in repair mode

For a significant step, the specification should follow `!planning/chatgpt/02-implementation-spec-template.md`.

## Load project guidance

Before editing:

1. Read every applicable `AGENTS.md` or `AGENTS.override.md` file discovered from the repository root to the working directory.
2. Read the approved specification.
3. Read relevant documents in `!planning/decisions/`, `!planning/architecture/`, `!planning/scope/`, and `!planning/product/`.
4. Read relevant files referenced by the root `AGENTS.md`, including current migration and implementation plans when applicable.
5. Inspect nearby source code, tests, fixtures, configuration, and migrations.

Use repository documentation as the source of truth. Do not substitute remembered conversation context for current files.

## Establish repository state

Record before work:

- current branch
- current HEAD
- expected base and starting HEAD, if supplied
- working-tree status
- pre-existing local changes

Do not discard, overwrite, stage, or reformat unrelated pre-existing changes. If they overlap the task and cannot be preserved safely, stop and report the conflict.

## Validate the specification

Compare the approved specification with the actual checkout.

Private implementation details may be adapted to established repository patterns. Stop or request an explicit decision before changing:

- product behavior
- public API or persistent-data contracts
- schema or migration ownership
- authentication, authorization, roles, or account isolation
- financial calculations or invariants
- trust boundaries, secrets, sensitive-data handling, audit, or retention
- destructive, irreversible, rollback, or recovery behavior

If the specification is stale but the intended behavior is still clear, implement using the current equivalent repository structure and report the deviation.

## Classify scope and risk

Use `!planning/chatgpt/06-step-sizing-and-budget.md`.

Confirm that the task is one coherent capability. Do not expand an S or M task into an L or XL refactor without reporting the change in expected size and obtaining approval when it affects scope or contracts.

Treat auth, account isolation, migrations, destructive data behavior, financial invariants, imports, concurrency, external providers, and sensitive data as high risk even when the diff is small.

## Plan before coding

Create a concise internal execution plan that maps the specification to the current repository. Normally stage work as applicable:

1. contracts, errors, and typed models
2. persistence, migrations, repositories, and integrations
3. application services and domain rules
4. transport/API or UI integration
5. tests and fixtures
6. documentation and configuration

Use the smallest coherent sequence that keeps ownership and behavior clear.

## Implementation rules

- Reuse established abstractions and test helpers.
- Keep domain logic out of React components and transport handlers.
- Keep backend authorization at the owning backend boundary.
- Enforce account isolation in persistence or service access paths and test foreign-account behavior.
- Validate untrusted input at entry boundaries and enforce domain invariants in the owning layer.
- Keep transaction ownership explicit.
- Add locking, idempotency, deduplication, rollback, or recovery behavior when the specification requires it.
- Do not silently catch or translate errors in a way that changes stable error contracts.
- Do not edit historical migrations to hide drift.
- Do not add startup-time schema creation, migration stamping, or automatic upgrades.
- Do not add dependencies, frameworks, background-job systems, or parallel services unless approved by the specification.
- Do not weaken lint, format, type, test, validation, authorization, or security rules.
- Do not perform unrelated cleanup.

## Incremental validation

After each coherent stage, run the narrowest useful checks for the changed area.

Examples:

- a specific pytest file or test expression
- the affected module test group
- a focused TypeScript test
- schema, migration, or contract verification required by the change

Do not repeatedly run the full suite without first using failure output to identify and repair the root cause.

## Required test coverage

Apply the specification and project testing strategy. Cover relevant cases from this list:

- successful behavior
- malformed or invalid input
- missing resources
- authentication failure
- insufficient role
- foreign-account access
- duplicate or conflicting requests
- persistence and returned state
- transaction rollback and atomicity
- concurrency or locking
- idempotency and deduplication
- security and sensitive-data behavior
- regression of existing public contracts

Tests must prove behavior, not only implementation details.

## Full quality gate

Run the complete relevant quality gate before completion.

When `backend/python` is affected, normally run:

```bash
cd backend/python
uv run python scripts/check.py
```

Equivalent individual checks are:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

When frontend or TypeScript code is affected, run the checks required by the root `AGENTS.md` and repository scripts. Do not run a command known to interfere with an active local development process; report it as blocked and provide the safe verification alternative.

Run additional database, schema, migration, integration, or security checks required by the specification.

Never describe an unexecuted check as passed.

## Repair loop

For each failure:

1. identify the root cause from the smallest reproducible check
2. repair the implementation or test expectation according to the approved contract
3. rerun the failed targeted check
4. rerun the affected broader checks
5. rerun the full relevant gate after material repairs

Do not suppress an error, loosen an assertion, skip a test, or add a broad exception solely to make the gate green.

## Final diff audit

Inspect the complete diff before reporting completion. Remove or report:

- unrelated changes
- accidental whole-file formatting or line-ending churn
- generated files that are not required
- temporary debug code or logging
- secrets or sensitive data
- duplicated helpers or parallel abstractions
- unused compatibility layers
- undocumented dependencies
- unapproved changes to contracts, migrations, or security behavior

Compare the final result with every acceptance criterion.

## Output

Return the structure in `!planning/chatgpt/04-codex-final-report-template.md`.

Include exact commands and results, test counts, starting and final repository state, deviations, repairs, security and migration status, diff size when available, remaining risks, and PR readiness.

Use these result labels accurately:

- `PASS`: completed and verified
- `PASS WITH NOTES`: completed and verified with non-blocking disclosed limitations
- `BLOCKED`: cannot complete or verify because of a specific external or decision blocker
- `FAIL`: implementation or required verification remains failing
- `NOT RUN`: command was not executed

Do not claim merge readiness while blocking findings, failed checks, unapproved deviations, uncommitted changes, or unresolved specification conflicts remain.
