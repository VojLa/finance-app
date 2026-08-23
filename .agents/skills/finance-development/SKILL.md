---
name: finance-development
description: Implement Finance App changes in small verified slices with progressive testing, scoped review, and documentation impact analysis.
---

# Finance App development workflow

Use this skill for Finance App implementation, bug fixes, and code reviews after task triage. Follow the existing repository sources of truth; this workflow controls sequencing, not product scope.

## Workflow

`DISCOVER → DESIGN → IMPLEMENT → TARGETED TESTS → INTEGRATION TESTS → REVIEW → FIX → DELTA REVIEW → DOC IMPACT → DONE`

- **Discover:** follow `AGENTS.md`: rules, Project Map, relevant domain documentation, then a small set of code and tests. Identify the authoritative layer and invariants before editing.
- **Design:** skip for XS/S changes that have one clear local outcome. For M, write a short implementation and verification plan. L is decomposed into M-or-smaller slices; XL is fully decomposed and accepted before implementation begins.
- **Implement:** make one coherent behavior change per slice. Keep FastAPI routers and Next adapters thin. Python owns financial rules and authorization; PostgreSQL/SQLAlchemy/Alembic ownership remains explicit.
- **Test progressively:** choose the least expensive sufficient evidence first, then expand only when risk, changed boundaries, or failure requires it.
- **Review:** review the task and diff for correctness, security, data integrity, contracts, and invariant preservation before style.
- **Fix and delta review:** after a blocker fix, retest the blocker, inspect the changed diff, and check immediately related behavior. Do not repeat a full audit automatically.
- **Doc impact:** use `finance-docs` to update only affected maintained documentation or generated inventory.

## Progressive verification

Use this order as applicable: focused test → module/domain tests → integration/contract tests → static checks → full quality gate. A full suite is evidence for a broad or high-risk change, not a reflex after every small edit.

For TypeScript prefer `npx.cmd tsc --noEmit`, `npm.cmd test`, and `npm.cmd run lint`; do not run `npm run build` while `next dev` runs. For Python start from the relevant `uv run pytest` target in `backend/python`, then use Ruff, mypy, and the full backend check proportionately. API changes require OpenAPI/contract drift checking. Parser changes require a regression fixture. Database changes require the documented Alembic ownership and parity checks.

## Non-negotiable domain checks

- Money is `Decimal` with explicit currency and documented rounding; never `float`.
- Event-date FX values are distinct from current/snapshot FX values.
- Account isolation and authorization are enforced by Python, not the browser.
- Imports and provider inputs are untrusted; do not leak raw financial data, tokens, or internal errors.
- Migrations have one owner: Alembic. Do not alter archived Prisma migrations.
- Make transaction, idempotency, and concurrency boundaries explicit when touched.

Use `CHATGPT/WORKFLOW.md`, `CHATGPT/STEP-SIZING.md`, and the relevant planning decisions for detailed repository rules.
