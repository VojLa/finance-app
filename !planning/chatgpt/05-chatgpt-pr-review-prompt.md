# ChatGPT Pull-Request Review Prompt

Use this after Codex has completed local implementation, pushed the branch, and supplied its final audit report.

```text
Repository: VojLa/finance-app
Pull request: <PR_NUMBER_OR_BRANCH>
Approved specification: <PATH_OR_REFERENCE>
Codex final audit: <PASTE_OR_REFERENCE>

Review the pull request through GitHub against the approved specification and the current repository architecture. Do not modify code during the first review pass.

Preparation:

1. Read the complete PR metadata and changed-file list.
2. Read the relevant patches, not only the PR description.
3. Read the approved specification and the authoritative ADR, architecture, security, testing, and scope documents it depends on.
4. Inspect nearby unchanged code where needed to validate ownership, dependency direction, transaction behavior, and test coverage.
5. Treat the Codex audit as evidence to verify, not as proof.

Review dimensions:

- specification and acceptance-criteria coverage
- correctness of success and failure behavior
- public API and data-contract compatibility
- module ownership and dependency direction
- SOLID and DRY without unnecessary abstraction
- transaction ownership, rollback, atomicity, locking, concurrency, and idempotency
- authentication, authorization, role checks, and cross-account isolation
- untrusted-input validation, limits, logging, secrets, and sensitive data
- schema and migration ownership
- test quality, negative paths, regression coverage, and fixture realism
- error-code and status consistency
- accidental scope expansion, generated files, formatting churn, and dead code
- documentation and ADR updates
- agreement between claimed validation and repository/CI evidence

Finding severity:

- BLOCKER: unsafe to merge; security, data-loss, migration, contract, or fundamental correctness issue
- HIGH: likely defect or missing required behavior/test; must be fixed before merge
- MEDIUM: maintainability, edge case, or incomplete verification that should normally be fixed in this PR
- LOW: non-blocking improvement
- INFO: observation without requested change

Return the result in this order:

1. VERDICT
   - READY
   - READY AFTER MINOR FIXES
   - CHANGES REQUIRED
   - BLOCKED BY MISSING EVIDENCE
2. SPECIFICATION COVERAGE
   - each acceptance criterion: met / partial / missing / cannot verify
3. FINDINGS
   For every finding include:
   - severity
   - file and relevant line or symbol
   - observed behavior
   - why it matters
   - required correction
   - required regression test
4. ARCHITECTURE AND OWNERSHIP REVIEW
5. SECURITY REVIEW
6. DATABASE AND MIGRATION REVIEW
7. TEST AND VALIDATION REVIEW
8. DIFF HYGIENE REVIEW
9. POSITIVE OBSERVATIONS
10. EXACT CODEX REPAIR PROMPT
    - include only accepted blocking, high, and medium findings
    - preserve the original scope
11. MERGE CHECKLIST

Do not invent a finding only to fill a section. Say `No finding` when the reviewed evidence is sufficient.
```

## Merge checklist

- [ ] The PR implements one coherent capability.
- [ ] All acceptance criteria are met.
- [ ] No unapproved public-contract change exists.
- [ ] Module ownership and dependency direction are preserved.
- [ ] Authorization and account isolation are enforced on the backend.
- [ ] Untrusted inputs and sensitive data are handled according to risk.
- [ ] Migration ownership and historical migrations are preserved.
- [ ] Required success, failure, authorization, isolation, and regression tests exist.
- [ ] CI and local full quality gates are green or an explicit blocker is recorded.
- [ ] No unrelated refactor, debug code, secret, or accidental generated file remains.
- [ ] Required documentation and ADR updates are present.
- [ ] Remaining risks are acceptable and assigned to a later step when appropriate.

## Optional second-pass prompt

```text
Re-review PR <PR_NUMBER> after the repair commit.

Focus on whether each previously reported BLOCKER, HIGH, and MEDIUM finding is resolved without introducing a regression or expanding scope. Read the new patches and relevant tests. Return:

1. finding-by-finding resolution status
2. new findings, if any
3. validation evidence
4. final verdict: READY / CHANGES REQUIRED / BLOCKED
```
