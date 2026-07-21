# Step Sizing and Agentic-Usage Budget

## Purpose

This document keeps implementation steps small enough to design, implement, test, and review without duplicating excessive work between ChatGPT and Codex.

Changed-line counts are estimates, not quality metrics. A small security or migration change can be riskier than a large mechanical test update.

## Size classes

| Class | Typical changed lines | Typical shape | Default action |
|---|---:|---|---|
| S | 1-250 | one isolated behavior, test addition, documentation, or local refactor | one PR; direct GitHub implementation may be acceptable when low risk |
| M | 250-800 | one coherent capability across a few layers | preferred size for normal roadmap steps |
| L | 800-1,200 | broad capability, several layers, or substantial test coverage | require explicit staging and strong reason not to split |
| XL | over 1,200 | several contracts, migration plus feature work, or multiple capabilities | split before implementation unless the diff is mostly generated or mechanical |

These ranges describe the expected final diff, including tests and documentation.

## Risk can override line count

Treat a step as at least L-risk when it changes any of the following, even if the diff is small:

- authentication, session, authorization, or account isolation
- schema or migration ownership
- destructive data behavior or recovery
- financial calculations or financial invariants
- import deduplication, idempotency, or posting behavior
- concurrency, locking, or transaction boundaries
- secrets, sensitive-data handling, audit, retention, or external providers
- more than one public API or persistent-data contract

High-risk work does not always need more lines, but it needs a more complete specification, negative tests, and independent review.

## Splitting rules

Split a proposed step when two or more of these are true:

- it introduces multiple independent user-visible capabilities
- it changes more than one unrelated public contract
- it combines a schema migration, data backfill, and new endpoint behavior
- it touches unrelated domains or module owners
- it requires separate security decisions
- it cannot be rolled back or reviewed as one coherent unit
- the expected diff is above 1,200 changed lines and is not mostly test fixtures or mechanical generated output
- acceptance criteria naturally form independently deployable groups

Prefer vertical slices that leave the repository in a valid state:

```text
foundation contract -> persistence -> service -> endpoint -> tests
```

Do not split in a way that leaves an unused abstraction, unprotected endpoint, incomplete migration owner, or temporarily broken main branch.

## Recommended specification depth

### S step

- 300-800 words
- concise current-state verification
- explicit behavior and tests
- no extensive architecture restatement

### M step

- 800-1,800 words
- complete contract, persistence, security, and test sections
- expected affected areas and staged execution

### L step

- 1,500-3,000 words
- explicit dependency and ownership analysis
- migration/recovery and concurrency details where relevant
- clear internal stages that can be validated separately
- a written explanation of why splitting would be worse

Avoid full code bodies in a specification. Use short signatures, request/response examples, tables, or pseudocode only to remove ambiguity.

## Limit-efficient division of work

### Use ChatGPT for

- repository and roadmap analysis
- architecture and product decisions
- contract and acceptance-criteria design
- identifying missing negative cases
- final PR review

### Use Codex for

- local repository inspection
- implementation
- test execution
- repair loops
- diff cleanup
- exact local audit reporting

### Avoid duplicate work

- Do not ask ChatGPT to write a large implementation that Codex will substantially rewrite.
- Do not ask Codex to redesign settled contracts unless it finds a conflict with the repository.
- Do not repeat the full repository history in every prompt; point to authoritative files.
- Do not paste large code files when Codex can inspect them locally.
- Do not run the complete suite after every small edit. Run targeted checks during development and the full gate before completion.
- Do not repeatedly ask for broad repository audits when a focused symbol or module inspection is enough.

## Validation strategy by stage

1. Run the narrowest test for the code currently being changed.
2. Run the affected module or API test group after a coherent stage.
3. Run formatting, lint, and typing after implementation stabilizes.
4. Run the full relevant repository quality gate before completion.
5. Rerun the full gate after any repair that could affect broad behavior.

A failed full gate should trigger a focused root-cause repair, not repeated blind full-suite runs.

## Practical approval rule

Approve one roadmap step when all of the following are true:

- its objective fits in one sentence
- all changed behavior contributes to that objective
- acceptance criteria can be reviewed together
- one branch and one PR can represent the capability cleanly
- failure or rollback has one understandable boundary
- the expected diff is normally at most M, or L has an explicit justification

## Empirical calibration

The actual agentic usage depends on repository context, model, tool calls, test iterations, and defect rate. Track completed steps with `07-step-log-template.md` instead of assuming a fixed percentage per line.

After at least five comparable steps, calculate:

- median usage percentage per step
- median changed lines per step
- median Codex repair lines
- number of failed validation loops
- usage by size and risk class

Use medians rather than a single unusually easy or difficult pull request when estimating weekly capacity.
