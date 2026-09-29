# Bug fix: [observed failure]

## Contract

- Exact observed behavior, environment, and safe input:
- Expected behavior and authoritative source:
- Size/risk and acceptance owner:
- Exact write scope and non-goals:

## Reproduction and evidence

Provide the smallest deterministic reproduction and relevant sanitized failure
excerpt. Separate facts from hypotheses. If it is not reproducible, create a
read-only diagnostic assignment first.

## Root cause

Identify the owning layer, why the behavior occurs, and why existing tests missed it.
Do not fix an adjacent symptom.

## Repair

Make the smallest change that removes the cause. Add a regression test that fails
before the repair and passes afterward. Use exact `Decimal` values for money, a
foreign principal for access bugs, malformed/limit fixtures for imports, and
rollback/concurrency evidence for database behavior where relevant.

## Acceptance criteria

- [ ] Original reproduction fails before the repair.
- [ ] Regression test passes afterward.
- [ ] Unrelated contracts and files are unchanged.
- [ ] Proportionate verification and documentation impact are complete.
