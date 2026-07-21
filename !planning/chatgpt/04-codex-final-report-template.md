# Codex Final Report Template

Codex must return this report after implementation, verification, or a repair pass. Keep every heading. Use `NONE`, `NOT RUN`, or `BLOCKED` instead of omitting information.

```text
<STEP_ID> FINAL LOCAL AUDIT

STATUS
- Result: PASS / PASS WITH NOTES / BLOCKED / FAIL
- Specification: <path or reference>
- Scope completed: yes / partial / no

REPOSITORY STATE
- Repository: VojLa/finance-app
- Branch: <branch>
- Base branch: <base>
- Expected starting HEAD: <sha or not supplied>
- Actual starting HEAD: <sha>
- Final HEAD: <sha or uncommitted>
- Working tree before work: clean / modified
- Working tree after work: clean / modified
- Pre-existing changes preserved: yes / no / none present

IMPLEMENTATION SUMMARY
- <Implemented capability>
- <Important behavior or invariant>
- <Important security or persistence behavior>

FILES CHANGED
- `<path>` - <reason>
- `<path>` - <reason>

DESIGN DECISIONS
- <Private implementation decision and why it follows repository patterns>

DEVIATIONS FROM SPECIFICATION
- NONE
or
- <Deviation>
  - Reason: <why>
  - User-visible or contract impact: <none or exact impact>
  - Approval required: yes / no

INCOMING DEFECTS FOUND
- NONE
or
- <Defect found before repair>

REPAIRS MADE
- NONE
or
- <Repair and affected behavior>

SECURITY AND AUTHORIZATION
- Authentication boundary: <verified behavior or not relevant>
- Authorization roles: <verified behavior or not relevant>
- Account isolation: <verified behavior or not relevant>
- Untrusted input and limits: <verified behavior or not relevant>
- Sensitive data and logging: <verified behavior or not relevant>
- Security tests added or run: <list>

DATABASE AND MIGRATION STATE
- Schema changed: yes / no
- Migration owner respected: yes / no / not relevant
- Migration files added: <list or none>
- Historical migrations modified: no / yes with explanation
- Forward verification: <result>
- Rollback/recovery consideration: <result or not relevant>

TARGETED VALIDATION
- `<exact command>`: PASS / FAIL / BLOCKED / NOT RUN
  - Result: <test count, output summary, or blocker>
- `<exact command>`: PASS / FAIL / BLOCKED / NOT RUN
  - Result: <test count, output summary, or blocker>

FULL QUALITY GATE
- Dependency installation/sync: PASS / FAIL / BLOCKED / NOT RUN
- Ruff lint: PASS / FAIL / BLOCKED / NOT RUN
- Ruff format: PASS / FAIL / BLOCKED / NOT RUN
- Mypy: PASS / FAIL / BLOCKED / NOT RUN
- Pytest: PASS / FAIL / BLOCKED / NOT RUN
  - Passed: <count>
  - Failed: <count>
  - Skipped: <count>
- Frontend tests: PASS / FAIL / BLOCKED / NOT RUN
- Frontend lint: PASS / FAIL / BLOCKED / NOT RUN
- Frontend format check: PASS / FAIL / BLOCKED / NOT RUN
- Frontend build: PASS / FAIL / BLOCKED / NOT RUN
- Database verification: PASS / FAIL / BLOCKED / NOT RUN
- Other required checks: <exact command and result>

DIFF AUDIT
- Unrelated changes: none / <list>
- Formatting-only churn: none / <list>
- Generated files: none / <list and justification>
- Debug code or temporary logging: none / <list>
- New dependencies: none / <list and justification>
- Secrets or sensitive data introduced: no / yes with immediate blocker

SIZE
- Files changed: <count>
- Insertions: <count or unavailable>
- Deletions: <count or unavailable>
- Total changed lines: <count or unavailable>
- Size class after implementation: S / M / L / XL

ACCEPTANCE CRITERIA
- [x] <criterion>
- [ ] <criterion not met and why>

REMAINING RISKS AND FOLLOW-UP
- NONE
or
- <Risk, severity, and recommended follow-up step>

PR READINESS
- Ready to commit: yes / no / already committed
- Ready to push: yes / no / already pushed
- Ready for ChatGPT review: yes / no
- Ready to merge: yes / no, pending independent review and CI
```

## Reporting rules

- Report actual commands, not paraphrases such as "tests passed".
- Never convert a skipped or unavailable check into a pass.
- Separate an environmental blocker from an implementation failure.
- Report test counts when the runner provides them.
- Report all material deviations even when tests pass.
- A clean working tree does not prove correctness; include the executed validation evidence.
- `Ready to merge` must remain `no` when blocking findings, failed checks, unapproved deviations, or uncommitted changes remain.
