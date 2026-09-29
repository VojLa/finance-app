---
name: finance-development
description: "Implement or review a bounded Finance App change with progressive verification, invariant preservation, and an explicit handoff."
---

# Finance App development

Use after `finance-orchestrator` has defined the outcome, scope, authority,
invariants, acceptance criteria, and verification route.

## Execution loop

`DISCOVER → DESIGN IF NEEDED → IMPLEMENT → TARGETED VERIFY → EXPAND VERIFY → REVIEW → FIX → DELTA REVIEW → DOC IMPACT`

- **Discover:** read only the exact paths in the context capsule. Read an imported
  contract or adjacent test only when its exact path is pre-allowlisted and report
  the path; otherwise stop before opening it. Never open a second domain or a broad
  directory without a new manifest from the primary.
- **Design:** skip for a clear XS/S. For M, record the layer boundary, failure
  behavior, and verification. Return L/XL work to the orchestrator for decomposition.
- **Implement:** make one coherent behavior change. Keep FastAPI routers and Next.js
  adapters thin; do not create empty layers or unrelated refactors.
- **Verify:** start with the cheapest test that can falsify the change. Expand to
  module, integration/contract, static, and full gates only as risk requires.
- **Review:** check correctness, security, data integrity, contracts, invariants,
  and test quality before style.
- **Fix:** retest the blocker and directly coupled behavior, then inspect only the
  delta introduced by the fix.
- **Handoff:** use `.agents/templates/IMPLEMENTATION-OUTPUT.md`; never hide an
  unverified criterion or scope expansion.

## Non-negotiable boundaries

- Python owns finance rules, object-level authorization, and account isolation.
- Money uses `Decimal`, explicit currency and rounding; event-date FX is not current
  or snapshot FX.
- SQLAlchemy is the complete runtime mapping and Alembic is the sole executable
  migration owner. Never edit archived Prisma migrations.
- Imports and providers are untrusted; keep tokens, secrets, raw imports, and
  unnecessary financial payloads out of logs.
- Make transaction, rollback, idempotency, lease, and concurrency behavior explicit
  when relevant.
- Generated files are changed only through their generator.

API changes require OpenAPI/contract evidence; parser changes require a regression
fixture; schema changes require Alembic graph, artifact, and SQLAlchemy parity
checks. Use `.agents/WORKFLOW.md` for the project verification ladder.
