# Implementation Specification Template

Copy this template for every significant roadmap step. Remove sections that are genuinely irrelevant; do not leave material decisions as empty placeholders.

```markdown
# <STEP_ID> - <STEP_TITLE>

## Metadata

- Status: proposed / approved / implemented
- Base branch: `main`
- Expected starting HEAD: `<SHA_OR_TO_BE_VERIFIED>`
- Implementation branch: `<TYPE>/<SHORT_NAME>`
- Size class: S / M / L / XL
- Expected changed lines: `<RANGE>`
- Preceding step or dependency: `<STEP_OR_NONE>`

## Objective

<One paragraph describing the capability that must exist after this step and why it is needed now.>

## Confirmed current state

- `<Current implementation fact with file or contract reference>`
- `<Current test or migration fact>`
- `<Relevant architecture, ADR, scope, or security rule>`

## Problem being solved

<Describe the missing behavior, inconsistency, risk, or architectural gap.>

## Scope

### In scope

- `<Required behavior>`
- `<Required layer or contract change>`

### Out of scope

- `<Explicitly deferred behavior>`
- `<Nearby refactor that must not be included>`

## Required behavior

1. `<Observable behavior or invariant>`
2. `<Observable behavior or invariant>`
3. `<Failure or edge-case behavior>`

## Design constraints

- Reuse: `<Existing services, repositories, models, fixtures, helpers, or conventions>`
- Dependency direction: `<Allowed ownership and imports>`
- Compatibility: `<Backward-compatibility requirement>`
- Prohibited shortcuts: `<Examples: parallel service, runtime schema creation, weakened validation>`

## Public and internal contracts

### API or transport

- Method and path: `<METHOD /api/... or none>`
- Authentication: `<Required principal/session>`
- Authorization: `<Roles and account boundary>`
- Request: `<Fields, types, constraints>`
- Success response: `<Status and body>`
- Error responses: `<Stable status/code/body expectations>`

### Application service

- Entry point: `<Service or use-case contract>`
- Inputs: `<Typed inputs>`
- Output: `<Typed result>`
- Invariants: `<Rules owned by the service>`

### Persistence

- Models/tables affected: `<List or none>`
- Repository operations: `<Reads, writes, locks, filters>`
- Transaction owner: `<Layer responsible for commit/rollback>`
- Concurrency/locking: `<Expected behavior>`
- Idempotency/deduplication: `<Expected behavior>`

## Schema and migration impact

- Schema change required: yes / no
- Current migration owner: `<Verify against repository documentation>`
- Migration files: `<Expected path or none>`
- Forward verification: `<Command or test>`
- Rollback/recovery consideration: `<Required behavior>`
- Existing historical migrations must not be edited.

## Security assessment

- Protected assets: `<Data or operation>`
- Allowed actors: `<Roles/principals>`
- Account isolation: `<How foreign-account access is prevented and tested>`
- Untrusted input: `<Validation and limits>`
- Sensitive data: `<What must not appear in logs or responses>`
- Abuse scenarios: `<Relevant misuse cases>`
- Security tests: `<Required negative cases>`

## Error handling

| Situation | HTTP/status behavior | Stable error code | Persistence effect |
|---|---|---|---|
| `<case>` | `<result>` | `<code>` | `<none/rollback/etc.>` |

## Implementation stages

1. `<Contracts, types, or models>`
2. `<Persistence or integration>`
3. `<Application service>`
4. `<Transport/API>`
5. `<Tests>`
6. `<Documentation/configuration>`

After each stage, run the narrowest useful checks before continuing.

## Expected affected areas

These paths are guidance, not permission to ignore the actual repository structure.

- `<path or module>`
- `<path or module>`

## Required tests

### Success

- `<Happy-path scenario and assertion>`

### Validation and domain failures

- `<Invalid input or invariant>`

### Authorization and isolation

- `<Unauthenticated or wrong role>`
- `<Foreign account/resource>`

### Persistence, atomicity, and concurrency

- `<Commit/rollback/locking/idempotency scenario>`

### Regression

- `<Existing behavior that must remain unchanged>`

## Acceptance criteria

- [ ] `<Testable behavior>`
- [ ] `<Testable behavior>`
- [ ] Required targeted tests pass.
- [ ] Required full quality gate passes.
- [ ] No unrelated diff or generated-file churn remains.
- [ ] Documentation and ADRs are updated when required.
- [ ] Final report contains exact commands, results, and deviations.

## Validation commands

Run from the specified directories.

```bash
# Targeted checks during implementation
<COMMANDS>

# Full backend gate when backend/python is affected
cd backend/python
uv run python scripts/check.py

# Full frontend gate when frontend/TypeScript is affected
cd <REPOSITORY_ROOT>
npm run test
npm run lint
npm run format:check
npm run build
```

Do not claim a command passed when it was not executed. Mark unavailable external checks as `BLOCKED` with the exact reason.

## Deviation policy

Codex may adjust private implementation details to match established repository patterns. Codex must stop or explicitly report before changing:

- product behavior
- a public API or data contract
- schema or migration ownership
- authorization or account-isolation rules
- financial invariants
- security boundaries
- destructive or irreversible behavior

## Required final output

Use `!planning/chatgpt/04-codex-final-report-template.md` exactly enough that every section can be audited.
```
