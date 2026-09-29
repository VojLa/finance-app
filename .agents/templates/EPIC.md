# Epic: [cross-domain outcome]

## Outcome and boundary

State user value, affected domains, data owner, current/target authority, and explicit
non-goals. Identify temporary adapters and their removal condition.

## Decisions before implementation

List unresolved API, module, schema/Alembic, auth/account-isolation, money/FX,
import/provider, transaction, concurrency, recovery, and observability decisions.
Create or reference ADRs for durable choices.

## Risk and rollout

Cover security, data loss, financial precision, historical FX, compatibility,
performance, concurrency, migration/backfill, rollout, rollback, and recovery.

## Dependency plan

| ID | One observable outcome | Size/score | Depends on | Risk | Model/effort | Write owner | Verification |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| X.1 | | M/6 | | medium | Sol/medium | | |

Order work as decision → compatible contract → vertical slices → Alembic
migration/backfill → integration/security evidence → old-path removal. Mark only
independent, non-overlapping steps as parallel.

## Definition of done

- Every step has accepted binary criteria and proportionate evidence.
- Python/Next.js authority, SQLAlchemy mapping, and Alembic-only migration ownership
  remain explicit.
- Migration, rollback/recovery, auth, account isolation, and finance invariants have
  positive and negative evidence where relevant.
- Temporary paths are removed or have an owned follow-up.
- Documentation and user-facing behavior are current.
