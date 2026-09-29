# Plan: [decision or initiative]

Do not implement while producing this plan.

## Problem and outcome

- Current behavior and owner:
- Observable target:
- Explicit non-goals:
- Size/risk and why planning is required:

## Authority and constraints

- Current docs and accepted decisions:
- Public/API/data contracts:
- Auth, money/FX, imports, schema, data-loss, transaction, and concurrency impact:

SQLAlchemy is the complete runtime mapping and Alembic is the sole executable
migration owner. Archived Prisma migrations are immutable and never a target path.

## Options

Compare at most three realistic options. For each include layer ownership, contract
and data impact, security, transaction/concurrency behavior, rollout/recovery,
verification, and complexity.

## Recommendation

Choose one option, explain the trade-off, and identify decisions requiring an ADR,
Sol consultation, or user confirmation.

## Decomposition

Split the recommendation into dependency-ordered S/M steps. Each step has one
outcome, exact ownership, risk, binary criteria, verification, and model/effort.
Mark which steps can run concurrently without file or dependency overlap.
