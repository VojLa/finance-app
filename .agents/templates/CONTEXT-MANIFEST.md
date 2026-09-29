# Worker context manifest: [task]

## Assignment

- Worker role: scout | implementer | tester | reviewer
- Model/effort:
- Observable outcome:
- Size/risk:
- Depends on:
- Exact failing scenario or question to prove:

## Conversation capsule

- User outcome:
- Explicit decisions already made:
- Non-goals:
- One unresolved question, if any:

Do not attach the full chat, prior commentary, tool logs, or unrelated failed attempts.

## Authority

- Current owner:
- Required reading, exact paths only:
  - `memory/codex_rules.md`
  - [one domain owner or invariant]
  - [zero to two directly applicable decisions/invariants]
- Accepted decisions:
- Relevant invariants:

Do not read directory trees, all planning, all generated inventories, or `ChatGPT/`
history. One exact historical record may be included only when it is direct evidence.

## Scope and permissions

- Read scope: [exact files; for a scout, named roots plus exact search query/filter]
- Discovery result limit: not applicable | [maximum candidate paths/results]
- Write scope: read-only | [exact existing files and exact allowed new-file paths]
- Explicit non-goals:
- Another worker owns:
- Allowed read-only expansion paths: none | [up to two exact imported contracts or adjacent tests]

Do not rescan the repository or edit outside write scope. Open an additional path
only when it appears in the expansion allowlist and report it. If another file is
needed, return `BLOCKED` with the candidate path without opening it. Stop before
another domain or any non-allowlisted expansion.

## Acceptance criteria

- [ ] Binary criterion.
- [ ] Diff remains inside write scope.
- [ ] Required evidence is returned.

## Verification

- Focused command:
- Additional check only if:

## Stop conditions

Stop and report `BLOCKED` for a missing product choice, conflicting authority,
required write-scope expansion, external/destructive action, or plausible P0/P1
security, money, schema, data-loss, or concurrency defect.

## Required return

Return exactly the fields from `.agents/templates/WORKER-RESULT.md`. Do not declare
the parent initiative accepted.
