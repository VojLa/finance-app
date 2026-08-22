---
name: finance-app-dev-loop
description: Use for substantial design, implementation, debugging, testing, review, remediation, or release-audit work in the VojLa/finance-app repository. Orchestrates credit-efficient Codex work by scoping the task, selecting the cheapest capable model/subagent, implementing small vertical slices, escalating only when risk or ambiguity requires it, running tests progressively, and reviewing only the relevant diff or unresolved blockers instead of repeatedly re-auditing the whole repository.
---

# Finance App Development Loop

Run repository work as a bounded, evidence-driven loop. Optimize for correctness first and model/credit efficiency second. Do not duplicate project rules inside this skill; load the repository sources of truth only as needed.

## 1. Load the minimum required context

Always read `AGENTS.md` and `memory/codex_rules.md` before substantial work.

Then load only the material relevant to the task:

- `ChatGPT/STEP-SIZING.md` to classify XS/S/M/L/XL.
- `ChatGPT/WORKFLOW.md` for implementation and verification rules.
- `ChatGPT/MODEL-SELECTION.md` for capability-based model selection and escalation.
- Relevant sections of `!docs/` for current architecture and technical constraints.
- Relevant sections of `!planning/` for intended design, accepted decisions, roadmap, and scope.
- A matching `ChatGPT/steps/` or `ChatGPT/audits/` file when the task belongs to an existing step, remediation, or audit.

Do not bulk-read `!docs/`, `!planning/`, `ChatGPT/steps/`, or the repository. Start from indexes/search and open only files needed to resolve the current task.

If documentation and implementation disagree, identify the authoritative source before making a large change. Do not silently invent a new architecture.

## 2. Classify the requested work before acting

Determine:

- requested outcome;
- in-scope behavior;
- explicitly out-of-scope behavior;
- affected domain and layers;
- safety/data-loss/auth/financial/API/database/import/concurrency risk;
- step size using `ChatGPT/STEP-SIZING.md`;
- whether this is DESIGN, IMPLEMENT, FIX, VERIFY, REVIEW, AUDIT, or FULL_LOOP.

For XS and clear S tasks, skip a separate design phase unless the repository rules require one.

For M tasks, make a short implementation plan when multiple layers are involved.

For L tasks, do not implement the whole task in one pass. Split it into independently verifiable M-or-smaller slices.

For XL tasks, decompose first. Do not start implementation until there is a bounded sequence of steps.

## 3. Choose the cheapest capable worker

Use capability classes, not hard-coded commercial model names.

### Cheap worker

Use for:

- XS/S mechanical edits;
- formatting/lint/type fixes;
- straightforward test additions when behavior is already specified;
- documentation updates;
- small, unambiguous diff review.

### Standard worker

Default for:

- M implementation slices;
- localized debugging;
- routine backend/frontend changes;
- integration and regression tests;
- fixing concrete blockers found by review.

### Strong worker

Reserve for:

- L/XL decomposition and architecture decisions;
- unresolved source-of-truth conflicts;
- auth/account isolation;
- monetary invariants and FX semantics;
- schema ownership/cutover/migration design;
- import trust boundaries;
- concurrency/idempotency/transaction design;
- high-risk final review.

When Codex supports subagent/model delegation, delegate each phase to the cheapest class that satisfies it. Prefer forked/minimal-context subagents for routine work so they do not inherit unnecessary reasoning history.

Do not use a strong worker to perform routine implementation merely because it created the plan.

Escalate one class after a failed attempt only when the failure is due to reasoning/capability. If the failure came from missing context, wrong scope, bad test setup, or an unclear contract, fix that cause before retrying.

## 4. Establish a bounded task contract

Before implementation of M/L work, capture a concise contract containing:

- Goal
- Scope
- Out of scope
- Relevant files/modules
- Invariants/constraints
- Acceptance criteria
- Planned targeted tests
- Base ref/commit when reviewing an existing change

Keep the contract short. Reuse an existing step/audit document when one already defines the task. Do not create a second source of truth for the same requirement.

Acceptance criteria must be binary where practical. Separate BLOCKER requirements from NON-BLOCKER improvements.

Do not implement unrelated cleanup or desirable refactors unless they are required to satisfy the task.

## 5. Design phase for risky or large work

For tasks requiring design:

1. Trace only the relevant current flow.
2. Identify existing ownership boundaries and invariants.
3. Resolve ambiguities using `!docs/`, `!planning/`, and existing decisions.
4. Produce the smallest safe design.
5. Split implementation into independently testable slices.
6. Identify rollback/compatibility implications.
7. Define targeted tests before implementation begins.

The design phase must stop when the implementation contract is sufficiently specific. Do not keep exploring the repository after the relevant architecture is understood.

Persist long-lived architectural decisions in the repository's established planning/decision location when required by `ChatGPT/WORKFLOW.md`.

## 6. Implementation loop

Implement one bounded slice at a time.

For each slice:

1. Read only the files needed for that slice.
2. Make the smallest change satisfying the acceptance criteria.
3. Add or update targeted tests with the implementation.
4. Run the smallest relevant test/check first.
5. If it fails, diagnose the concrete failure and fix only that cause.
6. Re-run the focused check.
7. Expand verification only after focused checks pass.

Preserve the repository rules, especially around money, authorization, account isolation, imports, transaction boundaries, idempotency, concurrency, database ownership, and temporary scaffolding.

Do not repeatedly re-read the entire codebase between loop iterations.

## 7. Progressive verification pyramid

Use progressively broader verification instead of running every suite after every edit.

Typical order:

1. test for the changed function/behavior;
2. affected module/domain tests;
3. affected integration/contract tests;
4. lint/type/static checks relevant to the changed stack;
5. full quality gate once the slice is stable;
6. one final full gate after the last blocker fix when warranted.

Use the exact commands documented in `ChatGPT/WORKFLOW.md`, `AGENTS.md`, and repository scripts. Do not invent an alternative verification workflow without a reason.

If a broad suite fails:

- classify each failure as CAUSED_BY_CHANGE, PRE_EXISTING/UNRELATED, or UNKNOWN;
- fix CAUSED_BY_CHANGE failures;
- do not repair unrelated failures unless requested;
- reduce UNKNOWN failures to a reproducible local cause before escalating.

Avoid rerunning a full suite after every small fix. Re-run focused tests first, then the full gate when the fix is stable.

## 8. Review using deltas, not repeated global audits

For implementation review, inspect the task contract plus the relevant diff (`BASE..HEAD`, PR diff, or working-tree diff). Review correctness before style.

Check, according to risk:

- acceptance criteria;
- regression risk;
- auth/account isolation;
- monetary precision/currency semantics;
- data loss and rollback;
- transaction boundaries/idempotency/concurrency;
- API/OpenAPI compatibility;
- schema/migration ownership;
- import trust boundaries;
- test sufficiency;
- unintended out-of-scope changes.

Return findings as:

- BLOCKER: must be fixed before completion;
- NON-BLOCKER: improvement outside required scope;
- PASS: verified requirement with evidence.

When a review finds blockers, send only those blockers and relevant files/diff to the implementation worker. After fixes, review the new delta plus unresolved blockers. Do not restart a full repository audit unless the task explicitly calls for a final release audit or the change invalidated prior audit evidence.

For remediation programs, retain previously proven PASS items and re-check only unresolved/invalidated requirements. Run one terminal full audit when all remediation blockers are closed.

## 9. Context and output discipline

Keep context small:

- prefer exact file paths, symbols, failing tests, and diffs over broad repository scans;
- summarize prior findings instead of carrying verbose reasoning forward;
- provide a subagent only the contract, relevant source files, test failure, and required evidence;
- reuse stable repository instructions instead of restating them in every prompt.

Keep worker output concise. Unless detailed explanation is requested, completion output should contain only:

- STATUS: PASS / BLOCKED / PARTIAL
- SCOPE completed
- FILES changed
- TESTS/CHECKS run and result
- BLOCKERS remaining
- NEXT action, only if needed

Do not request long narratives from implementation workers.

## 10. Stop conditions

Stop the loop when all of the following are true for the requested scope:

- acceptance criteria are satisfied;
- targeted tests pass;
- required broader gates pass or unrelated failures are explicitly classified;
- review has no unresolved BLOCKER findings;
- diff contains no unintended scope expansion;
- required docs/decision records match the implementation;
- working tree/branch state is understood.

Do not continue polishing after these conditions are met.

Stop and report BLOCKED rather than guessing when a required product/architecture decision has no authoritative answer in the repository and cannot be safely inferred.

## 11. Git and PR boundaries

Do not rewrite history, force-push, merge, close PRs, or modify unrelated branches unless explicitly requested.

When asked to prepare a PR, report the exact base/head, summarize behavior changes, list verification evidence, and distinguish known unrelated failures from task regressions.

When asked only to design or review, do not implement code unless the user explicitly extends the scope.

## 12. Full-loop default for complex tasks

When the user asks Codex to complete a substantial task end-to-end, use this sequence:

1. **Scope/classify** — cheap or standard worker.
2. **Design/decompose** — strong worker only if risk/size requires it.
3. **Implement slice** — standard worker; cheap worker for mechanical subtasks.
4. **Focused verify/fix loop** — cheapest capable worker.
5. **Affected integration gate** — standard worker.
6. **Full quality gate** — run once near completion.
7. **Diff review** — strong worker only for high-risk changes; otherwise standard/cheap as appropriate.
8. **Blocker remediation** — standard/cheap worker using only blocker context.
9. **Delta re-review** — review only fixes and unresolved blockers.
10. **Terminal audit** — only when required by release/remediation scope.

The objective is not to minimize model quality. The objective is to spend strong-model reasoning only where it materially changes correctness, while keeping implementation and verification bounded, reproducible, and evidence-driven.
