# Codex Implementation Prompt

Use this prompt after the implementation specification has been approved. Keep this wrapper short; the detailed decisions belong in the specification and repository skill.

```text
Use the `$finance-app-implementation` skill.

Repository: VojLa/finance-app
Approved specification: <PATH_OR_PASTED_SPECIFICATION>
Target branch: <BRANCH_NAME>
Expected base: main
Expected starting HEAD: <SHA_OR_VERIFY_AND_REPORT>

Implement the approved specification in the local repository.

Mandatory execution rules:

1. Before editing, read the repository `AGENTS.md`, the approved specification, relevant planning/ADR/security documents, and nearby implementation and tests.
2. Report the actual branch, HEAD, and working-tree state. Do not discard pre-existing local changes.
3. Verify every important assumption in the specification against the checkout. Preserve the requested behavior, but follow established repository patterns for private implementation details.
4. Stop for a material decision if the specification conflicts with a public contract, schema ownership, authorization, account isolation, a financial invariant, security boundaries, or destructive behavior.
5. Implement only the approved scope. Do not add unrelated refactors, dependencies, generated files, or speculative abstractions.
6. Work in coherent stages and run targeted checks after each affected area.
7. Add or update all tests required by the specification. Do not weaken validation, typing, lint rules, or existing tests to obtain a green result.
8. Run the complete relevant quality gate before completion. Repair failures and rerun affected broader checks.
9. Inspect the final diff for accidental churn, debug code, secrets, sensitive data, temporary compatibility code, and scope expansion.
10. Return the exact report structure from `!planning/chatgpt/04-codex-final-report-template.md`.

Do not claim success for checks that were not actually executed. Use `NOT RUN` or `BLOCKED` with a reason when necessary.
```

## Variant for verification and repair only

Use this when ChatGPT has already implemented a small change through GitHub and Codex should only validate it locally.

```text
Use the `$finance-app-implementation` skill in verification-and-repair mode.

Repository: VojLa/finance-app
Branch to verify: <BRANCH_NAME>
Specification or PR: <REFERENCE>

Do not redesign or expand the change. Inspect the diff against the specification, run targeted and full relevant checks, repair defects required to satisfy the approved scope, and return the standard final report.

Separate in the report:

- defects found in the incoming implementation
- repairs made by Codex
- changed-line count before and after repair, when available
- remaining specification or architecture gaps
```

## Variant for review-fix pass

```text
Use the `$finance-app-implementation` skill.

Apply only the accepted findings from this review to branch `<BRANCH_NAME>`:

<PASTE_ACCEPTED_FINDINGS>

Preserve the approved specification. Run targeted checks for every fix, rerun the complete relevant quality gate, inspect the final diff, and return the standard final report. Do not address informational suggestions unless explicitly included above.
```
