# ChatGPT Step Design Prompt

Use this prompt when selecting and designing the next roadmap step. Replace all placeholders before sending it.

```text
Repository: VojLa/finance-app
Target roadmap step: <STEP_ID> - <STEP_NAME>
Expected base branch: main
Current implementation branch, if already created: <BRANCH_OR_NONE>

Inspect the current repository through GitHub and design this step, but do not implement it yet.

Required preparation:

1. Verify the current main HEAD and relevant open pull requests.
2. Read the active milestone scope, roadmap, development workflow, security strategy, coding standards, testing strategy, project structure, relevant ADRs, and the implementation created by preceding steps.
3. Inspect the existing code and tests in every layer likely to be affected.
4. Distinguish confirmed repository facts from inferences.
5. Do not rely on an older conversation summary when the repository can provide the current state.

Design requirements:

- Define one coherent capability for this step.
- Explain why the step belongs in the current milestone and how it follows the previous step.
- Specify in-scope and out-of-scope behavior.
- Identify public API, application-service, repository, model, database, event, and configuration contracts that may change.
- Define authorization, account-isolation, input-validation, audit/logging, sensitive-data, and abuse-case requirements.
- Identify transaction boundaries, concurrency behavior, idempotency, rollback, recovery, and compatibility requirements when relevant.
- Reuse established repository patterns and avoid parallel abstractions.
- State whether an ADR or architecture-document update is required before implementation.
- Propose tests for success, validation failure, missing resources, authorization failure, cross-account access, duplicate/conflicting requests, persistence, atomicity, and regression as applicable.
- List exact validation commands based on the repository, not generic guesses.
- Estimate the expected changed-line range and classify the step as S, M, L, or XL according to !planning/chatgpt/06-step-sizing-and-budget.md.
- Split the step before implementation if it mixes unrelated capabilities, multiple public-contract changes, or an unsafe amount of migration and feature work.

Return the result in this order:

1. STEP VERDICT
   - ready to specify / requires decision / should be split
   - recommended step name and branch name
2. CONFIRMED CURRENT STATE
   - relevant files, contracts, tests, and preceding behavior
3. PURPOSE AND USER OR ARCHITECTURE VALUE
4. SCOPE
   - in scope
   - out of scope
5. DESIGN
   - affected layers
   - public contracts
   - persistence and migration impact
   - authorization and security
   - error behavior
   - transaction, concurrency, and idempotency behavior
6. IMPLEMENTATION STAGES
7. REQUIRED TESTS
8. ACCEPTANCE CRITERIA
9. VALIDATION COMMANDS
10. RISKS, OPEN DECISIONS, AND STOP CONDITIONS
11. EXPECTED SIZE
12. COMPLETE CODEX-READY SPECIFICATION
   - populate the structure from !planning/chatgpt/02-implementation-spec-template.md
13. SHORT CODEX EXECUTION PROMPT
   - populate !planning/chatgpt/03-codex-implementation-prompt.md

Do not output complete implementation code. Small pseudocode or contract examples are allowed only when needed to remove ambiguity.
```

## Review questions before approval

Before giving the specification to Codex, confirm:

- Does every acceptance criterion describe externally observable or testable behavior?
- Are important negative paths defined, not just the happy path?
- Is the owner of every modified piece of data clear?
- Is the authorization boundary explicit?
- Does the proposal preserve current migration ownership?
- Are any decisions being hidden inside implementation details?
- Can Codex implement the step without inventing product behavior?
- Is the step small enough to review as one pull request?
