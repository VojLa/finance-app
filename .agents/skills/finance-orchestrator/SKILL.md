---
name: finance-orchestrator
description: "Triage and coordinate non-trivial Finance App work with bounded context, Sol-led acceptance, cost-aware delegation, and evidence-based escalation."
---

# Finance App orchestrator

Use this skill before non-trivial Finance App implementation, review, debugging,
documentation, or architecture work. It chooses the execution shape; domain rules
remain in `!docs/`, `!planning/`, and `memory/codex_rules.md`.

## Triage

1. Read `memory/codex_rules.md`, one project map, one domain map, the linked current
   owner, and directly related code/tests.
2. State the observable outcome, non-goals, source of truth, affected domain, size,
   risk, acceptance criteria, and cheapest meaningful verification.
3. Identify API, schema, auth/account-isolation, money/FX, import, data-loss,
   transaction, idempotency, lease, or concurrency impact.
4. Choose one route:
   - **DIRECT:** obvious XS/S work or a task with no independently useful subtask;
   - **DELEGATE:** bounded, independently verifiable work with explicit ownership;
   - **ESCALATE:** an unresolved high-risk decision or material conflict in authority.

Read `.agents/STEP-SIZING.md` only when size is unclear. Read
`.agents/MODEL-ROUTING.md` when selecting or escalating a worker.

## Acceptance ownership

The primary orchestrator is the sole acceptance owner. It retains the original
criteria, cross-domain decisions, and dependency order. A worker may report
`COMPLETE`; it cannot declare the initiative accepted.

After each result, the primary checks:

- the requested outcome and every binary criterion;
- changed files against write scope;
- verification evidence and remaining risks;
- conflicts with current docs, accepted decisions, or adjacent contracts;
- documentation impact.

Use `.agents/templates/ACCEPTANCE-REVIEW.md` for an initiative checkpoint.

## Delegation

Delegate only reconnaissance, a deterministic documentation task, one coherent M
slice, focused tests, localized debugging, or an independent diff review.

Before delegating, compile a context capsule according to
`.agents/CONTEXT-POLICY.md`. Pass decisions and acceptance criteria as concise facts;
do not make the worker reconstruct them from chat history or broad documentation.

- Run at most two workers concurrently by default.
- Do not assign overlapping write scopes; one agent owns each edited file.
- Scouts and reviewers are read-only unless explicitly authorized to edit.
- Use `.agents/templates/CONTEXT-MANIFEST.md` for every worker.
- Require `.agents/templates/WORKER-RESULT.md` as the return schema.
- Use `fork_turns: "none"` for every bounded worker. Never use a full-history fork
  for reconnaissance, implementation, tests, documentation, or review.
- Name exact documents and files. Do not assign directory-wide reading, generic
  repository discovery, or historical chat reconstruction.
- Reuse the same worker for a delta review or blocker follow-up; do not repeatedly
  create reviewers. A follow-up receives only changed files, new evidence, remaining
  criteria, and the requested delta.

Workers stop on missing product authority, conflicting decisions, a required path
outside the manifest allowlist, destructive/external action, or a plausible
P0/P1 security, money, schema, data-loss, or concurrency problem.

## Model policy and escalation

Prefer a `gpt-6-sol` medium primary. Use `gpt-6-luna` for bounded deterministic
work and `gpt-6-sol` high or xhigh for difficult implementation and review.
`gpt-6-astra` is exceptional: use it only for a narrow question still unresolved
after a focused Sol xhigh attempt, or for an immediate credible P0/security/data-loss
emergency. High risk or large scope alone is not an Astra trigger. Explicitly set a
bounded worker's model and effort with `fork_turns: "none"`, so it does not inherit
an Astra primary. See `.agents/MODEL-ROUTING.md` for the full gates.

Escalate only with a packet containing new evidence: the exact decision or failure,
authoritative references, a minimal reproduction or failing assertion, attempted
work, and the requested decision. Use `.agents/templates/ESCALATION-PACKET.md`.
Never resend the same broad prompt to a stronger model.

## Completion

Finish only when the acceptance owner confirms the criteria, proportionate checks
pass, the diff is in scope, no blocker remains, and the `finance-docs` impact check
is complete. After a fix, review the delta and directly coupled behavior rather
than restarting the whole audit.
