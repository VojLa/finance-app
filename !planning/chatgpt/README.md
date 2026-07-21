# ChatGPT + Codex Development Workflow

## Purpose

This folder defines the repeatable workflow used to design and implement further roadmap steps in `finance-app`.

The goal is to avoid doing the same work twice:

- ChatGPT inspects the repository through GitHub, closes design decisions, and produces an implementation specification.
- Codex works in the local repository, implements the approved specification, runs checks, and repairs failures.
- ChatGPT reviews the resulting pull request against the specification and project architecture.

This workflow supplements `!planning/architecture/11-development-workflow.md`. It does not replace architecture, security, scope, or ADR documentation.

## Source-of-truth order

When instructions conflict, use this order:

1. accepted ADRs in `!planning/decisions/`
2. architecture and security documents in `!planning/architecture/`
3. active milestone scope in `!planning/scope/`
4. product roadmap and release strategy in `!planning/product/`
5. approved step implementation specification
6. this workflow and its templates
7. assumptions made by ChatGPT or Codex

Do not silently override a higher-priority source.

## Standard flow

```text
Roadmap step selected
        |
        v
ChatGPT repository audit and step design
        |
        v
Approved implementation specification
        |
        v
Codex local inspection and implementation
        |
        v
Targeted checks, full quality gate, repair loop
        |
        v
Codex final audit report
        |
        v
ChatGPT pull-request review against specification
        |
        v
Merge after review and green checks
```

## Role boundaries

### ChatGPT owns

- reading the current repository state through GitHub
- locating relevant roadmap, scope, architecture, ADR, and security rules
- defining the purpose and boundaries of the next step
- resolving product and architecture questions before implementation
- producing acceptance criteria and required test scenarios
- creating a Codex-ready implementation specification
- reviewing the final pull request and identifying gaps

ChatGPT should not implement a large feature through GitHub when Codex will then re-read and substantially repair the same code. Direct GitHub implementation is reserved for small, isolated, low-risk changes.

### Codex owns

- checking the local branch and working tree
- validating the specification against the actual checkout
- inspecting nearby implementation and test patterns
- implementing the approved change
- running narrow checks during development
- running the complete relevant quality gate before completion
- repairing failures without weakening checks
- reporting exact commands, results, deviations, and remaining risks

Codex must not redesign product behavior or public contracts without documenting the conflict and stopping when the decision is material.

## Required artifacts for each significant step

A significant roadmap step should have:

1. a step design produced with `01-chatgpt-step-design-prompt.md`
2. an approved specification based on `02-implementation-spec-template.md`
3. a Codex execution prompt based on `03-codex-implementation-prompt.md`
4. a final Codex report following `04-codex-final-report-template.md`
5. a pull-request review using `05-chatgpt-pr-review-prompt.md`
6. an optional usage and size record based on `07-step-log-template.md`

The specification may live in the pull-request description, a GitHub issue, or a temporary file. Long-lived architecture decisions must still be written to the normal planning or ADR locations.

## Step sizing

Use `06-step-sizing-and-budget.md` before approving a step.

Default target:

- one coherent capability per pull request
- approximately 300-800 changed lines for a normal step
- split the work when the expected diff exceeds about 1,200 lines, changes several public contracts, or combines a migration with multiple unrelated features

Line count is only a planning signal. Security, schema ownership, financial invariants, and concurrency can make a small diff high risk.

## Definition of ready for Codex

A step is ready when:

- the objective is explicit
- current repository state has been verified
- in-scope and out-of-scope work are stated
- public contracts and persistence effects are known
- authorization and security expectations are stated
- acceptance criteria are testable
- required validation commands are known
- material unresolved decisions are listed as blockers rather than assumptions

## Definition of complete

A step is complete when:

- the implementation matches the approved specification or deviations are explicitly accepted
- targeted and full required checks have passed
- tests cover the required success, failure, authorization, and regression scenarios
- the final diff contains no unrelated churn or temporary debugging code
- the Codex final report is complete and truthful
- ChatGPT review reports no unresolved blocking findings
- the pull request is ready to merge under the repository development workflow

## Files in this folder

- `01-chatgpt-step-design-prompt.md` - prompt for designing the next step
- `02-implementation-spec-template.md` - canonical technical specification template
- `03-codex-implementation-prompt.md` - short execution prompt for Codex
- `04-codex-final-report-template.md` - required Codex completion report
- `05-chatgpt-pr-review-prompt.md` - final review prompt and checklist
- `06-step-sizing-and-budget.md` - sizing and usage-efficiency rules
- `07-step-log-template.md` - optional empirical log for future capacity estimates

The repository-scoped Codex skill is stored at:

```text
.agents/skills/finance-app-implementation/SKILL.md
```
