# ADR 0015 - Import reconciliation evidence foundation

Status: Accepted
Date: 2026-08-19
Decision owners: Finance application architecture
Supersedes: none
Superseded by: none

## Kontext

Raiffeisenbank statement reconciliation needs durable, independently auditable
source occurrence identity, exact reporting-currency evidence, and a job scope
that is not inferred from mutable JSON payloads. Existing imports and
transaction pairs are historical financial evidence and must remain readable.

## Rozhodnuti

Alembic revision `3p0001rbfoundation` adds four schema-only tables:

- `ImportSourceOccurrence` identifies one account/source/fingerprint/ordinal
  occurrence and pins its representative import row and optional canonical
  transaction.
- `TransactionReportingEvidence` stores source money/time, reporting money,
  one direct persisted `ExchangeRate`, calculation version, optional job, and
  publication time for one transaction.
- `ImportJobBatch` and `ImportJobAffectedAccount` normalize the durable job's
  exact batch and authorized affected-account membership.

Composite foreign keys enforce source/account/batch, transaction/account, FX
direction, job/user/account, and account-member relationships. `TransactionPair`
adds nullable classification, source, evidence version/hash, job, and publication
fields. Legacy rows remain all-null; any non-legacy evidence must include the
complete versioned, SHA-256-hashed classification/source evidence set.

## Dusledky

- Future reconciliation and reporting services can validate persisted scope
  without treating job JSON as an authority.
- The foundation does not match rows, assign classifications, calculate money,
  or create canonical transactions; those remain later bounded steps.
- Downgrade is refused once any new durable evidence exists, avoiding loss of
  financial provenance.

## Zamitnute alternativy

- Storing reconciliation state only in `BackgroundJob.payload` was rejected
  because payload is bounded workflow state, not relational audit evidence.
- Rewriting all historical `TransactionPair` rows was rejected because legacy
  provenance cannot be invented truthfully.
- An FX ID-only relation was rejected because it cannot prove the direction
  used to calculate reporting money.

## Migracni nebo rollout plan

Upgrade is additive and preserves all legacy data. New writers must populate
the normalized membership rows and exact evidence atomically. A later service
step owns writer validation and public behavior; this ADR introduces neither.
