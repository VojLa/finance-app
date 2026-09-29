# Codex Local Instructions

Read this file before answering or changing code in this repository.

## Sources of truth

- `!docs/` owns the currently implemented technical system.
- `!planning/` owns future scope, accepted decisions, roadmap, and target design.
- `.agents/` owns the active Codex workflow, skills, model routing, and templates.
- `!user-docs/` owns end-user guidance.
- `ChatGPT/` contains historical steps and audits; it is evidence, not current instruction.
- `memory/codex_rules.md` contains the small set of persistent repository rules.

Runtime code, tests, live OpenAPI, and Alembic schema evidence prevail over stale prose.

## Minimum context

The primary agent loads the complete context needed for the initiative, not the
entire documentation tree:

1. Read `memory/codex_rules.md`.
2. Select one project map from `!docs/map/project-map/` and one domain map from
   `!docs/map/domain-map/`.
3. Read the linked current domain document, applicable invariant or flow, target
   code, and directly related tests.
4. Read `!planning/` only when the request changes future scope, an accepted
   decision, a public contract, an architectural boundary, or a high-risk rule.
5. For non-trivial work, apply `.agents/skills/finance-orchestrator/SKILL.md`.
   For implementation use `finance-development`; finish with `finance-docs`.

Use generated inventories for exhaustive file, route, model, and test discovery.

## Orchestration policy

The preferred default primary orchestrator is `gpt-6-sol` at medium reasoning. The
primary agent is the initiative's sole acceptance owner: workers report evidence,
but only the primary compares the result with the original acceptance criteria and
declares the initiative complete.

For a non-trivial task with independently verifiable work, explicitly use bounded
subagents. Do not delegate an obvious XS/S task when coordination would cost more
than direct execution.

- `gpt-6-luna`: reconnaissance, inventories, mechanical edits, known focused tests, and
  deterministic documentation.
- `gpt-6-sol`: triage, synthesis, ordinary M implementation, localized debugging, and
  integration work.
- `gpt-6-astra`: exceptional narrow consultation only when a focused Sol xhigh
  attempt remains unresolved, or for a credible active P0/security/data-loss emergency.

Risk overrides size. A high-risk change with an already accepted invariant may be
implemented and independently reviewed by Sol. An unresolved high-risk decision
gets a focused Sol consultation first; risk or size alone does not trigger Astra.
See `.agents/MODEL-ROUTING.md` for escalation gates and reasoning effort.

Run at most two workers concurrently by default. Parallel workers must be
independent and must not edit overlapping files. Assign one writer per file; scouts
and reviewers are read-only unless their manifest explicitly grants write scope.

## Delegated worker contract

Use `.agents/templates/CONTEXT-MANIFEST.md`. Every worker receives the outcome,
exact scope and write authority, relevant decisions and invariants, acceptance
criteria, verification command, stop conditions, and required result format.

A bounded worker receives a context capsule, never a directory-sized reading task.
The capsule names exact paths and normally contains `memory/codex_rules.md`, one
domain or invariant owner, zero to two directly applicable decisions/invariants,
target files, and directly related tests. Do not tell a worker to read all of
`!docs/`, `!planning/`, a domain tree, generated inventories, or repository history.
Historical `ChatGPT/` material is excluded unless one exact record is evidence for
the assigned question.

Use `fork_turns: "none"` for every bounded worker, including same-model workers.
Choose its model and effort explicitly; omitted overrides may inherit an Astra primary.
Transfer conversation context through a short manifest capsule containing only the
user outcome, explicit decisions, non-goals, unresolved question, and relevant
acceptance criteria. Do not forward prior commentary, tool logs, failed attempts, or
the full chat transcript. Reuse a worker for delta review with only the changed-file
manifest and new evidence. A similar domain is not sufficient for reuse; reuse a
worker only for the same initiative, acceptance criteria, and bounded workstream.

The detailed reading and expansion rules are in `.agents/CONTEXT-POLICY.md`. A
worker must not rescan the repository. It stops and reports when it needs a product
choice, finds conflicting authority, needs a path outside its context allowlist,
requires files outside write scope, or encounters a possible P0/P1 data, security,
money, schema, or concurrency defect.

## Repository invariants

- Keep changes small, reversible, and within explicit scope.
- Python owns financial rules, authorization, and account isolation; Next.js is
  presentation and same-origin transport.
- Money uses `Decimal`, explicit currency and rounding. Event-date FX is distinct
  from current or snapshot FX.
- SQLAlchemy is the complete runtime mapping and Alembic is the only executable
  migration owner. `prisma/migrations/` is an immutable historical archive.
- Imports and provider data are untrusted. Do not log secrets, tokens, raw imports,
  or unnecessary financial data.
- Make transactions, rollback, idempotency, leases, and concurrency explicit when
  touched.
- Record durable architectural decisions in `!planning/decisions/` before or with
  implementation. Mark temporary scaffolding and its removal condition.

## Verification

Use the smallest relevant check first, then expand in proportion to risk. For
TypeScript prefer `npx.cmd tsc --noEmit`, `npm.cmd test`, and
`npm.cmd run lint`. Do not run `npm run build` while `next dev` is active because
both share `.next`. Python and database checks are defined by the owning domain and
`.agents/WORKFLOW.md`.
