---
name: finance-orchestrator
description: "Triage and coordinate Finance App work: classify scope and risk, load the smallest useful context, delegate bounded work, and choose the least costly adequate model and reasoning effort."
---

# Finance App orchestrator

Use this skill before a non-trivial Finance App task. Its purpose is to choose a safe, inexpensive execution shape; it is not a replacement for implementation or domain guidance.

## Start with bounded context

1. Read `memory/codex_rules.md` and `!docs/map/PROJECT-MAP.md`.
2. Load the relevant domain section, its linked current documentation, and only the code needed to understand the change.
3. Classify the request by kind: reconnaissance, documentation, bug fix, implementation, refactor, test, review, or architecture/decision.
4. State the visible outcome, affected domain, explicit non-goals, and any API, database, auth, import-boundary, concurrency, or financial-invariant impact.

## Size and risk

Use these sizes as an execution decision, not as an estimate of calendar time:

| Size | Meaning | Execution rule |
| --- | --- | --- |
| XS | One obvious local change | Implement directly after discovery. |
| S | One localized behavior or documentation change | Implement directly; use a focused check. |
| M | One coherent vertical slice across necessary layers | Make a short design and one bounded implementation step. |
| L | Several dependent M slices or an unresolved boundary | Decompose before implementation. |
| XL | Cross-domain, migration, or product/architecture initiative | Complete a dependency plan and acceptance criteria before any slice starts. |

Mark risk as low, medium, or high. High risk includes money or currency arithmetic, source of truth, schema/migrations, authentication or account isolation, imports/untrusted files, concurrency/idempotency, data loss, and public contracts. Read the linked invariants before changing a high-risk domain.

## Model and reasoning selection

Assign the least capable adequate worker. Keep prompts narrow: outcome, exact files or map links, constraints, acceptance criteria, and targeted verification.

| Work | Default |
| --- | --- |
| Search, inventory, mechanical edits, format/lint, focused checks, simple documentation | Luna, low or medium |
| Normal M implementation, localized debugging, integration tests, blocker fix | Terra, medium or high |
| Architecture, high-risk invariants, auth, database ownership, concurrency, L/XL decomposition, critical review | Sol, high or xhigh |

Escalate only after adding the missing evidence (contract, reproduction, failing assertion, or decision). Escalate once per failure category: Luna low → Terra medium → Sol high. Do not repeat the same attempt or assign routine work to Sol just because it owns the task.

## Delegation and control

Delegate only independently verifiable, bounded work: reconnaissance, a single M slice, focused tests, deterministic documentation, or diff review. The orchestrator retains cross-domain decisions and merges results against the original acceptance criteria.

After each step, record only: completed outcome, changed files, verification result, unresolved blocker, and next owner. If a blocker is fixed, perform a delta review of the blocker, changed diff, and directly related behavior; do not restart a full audit unless scope or risk changed.

Finish when acceptance criteria hold, proportionate checks pass, the diff is in scope, and the Documentation Impact step is complete. Stop and ask for direction when a missing product choice, external authority, or irreversible action materially changes scope.
