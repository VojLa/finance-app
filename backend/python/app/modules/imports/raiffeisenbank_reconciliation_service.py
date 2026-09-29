"""Persist the pure RB reconciliation plan in its deliberately narrow boundary.

This module is not an executor stage.  A future workflow owner invokes it after
canonical posting, with the currently running import job as the sole publication
anchor.  Its repository discovers only that job and completed earlier jobs via
their durable manifests.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import ImportJobAffectedAccountModel
from app.db.models.enums import (
    AccountRelationType,
    ImportRowStatus,
    ImportSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel, ImportSourceOccurrenceModel
from app.db.models.transactions import TransactionModel, TransactionPairModel
from app.modules.imports.raiffeisenbank_reconciliation import (
    RaiffeisenbankPostedTransactionIdentity,
    RaiffeisenbankReconciliationAccount,
    RaiffeisenbankReconciliationCandidate,
    plan_raiffeisenbank_reconciliation,
)
from app.modules.imports.raiffeisenbank_reconciliation_repository import (
    RaiffeisenbankReconciliationEvidenceRow,
    RaiffeisenbankReconciliationRepository,
)

RECONCILIATION_EVIDENCE_VERSION = 1


class RaiffeisenbankReconciliationStateError(RuntimeError):
    """Durable state cannot safely be reconciled or replayed."""

    def __init__(self) -> None:
        super().__init__("Raiffeisenbank reconciliation evidence is unavailable.")


@dataclass(frozen=True, slots=True)
class ReconcileRaiffeisenbankJobCommand:
    job_id: str
    user_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RaiffeisenbankReconciliationResult:
    job_id: str
    pair_ids: tuple[str, ...]
    pairs_created: int
    pairs_replayed: int
    affected_account_ids: tuple[str, ...]


class _Repository(Protocol):
    async def load_current_and_completed_evidence_for_update(
        self, *, current_job_id: str, user_id: str
    ): ...

    async def lock_accounts_and_members(self, *, account_ids: tuple[str, ...], user_id: str): ...

    async def load_occurrences_for_update(
        self, *, representative_row_ids: tuple[str, ...]
    ) -> tuple[ImportSourceOccurrenceModel, ...]: ...

    async def load_pairs_for_update(self, *, transaction_ids: tuple[str, ...]): ...

    async def get_affected_account_for_update(
        self, *, job_id: str, account_id: str
    ) -> ImportJobAffectedAccountModel | None: ...

    def add_pair(self, value: TransactionPairModel) -> None: ...

    def add_affected_account(self, value: ImportJobAffectedAccountModel) -> None: ...

    async def flush(self) -> None: ...


class RaiffeisenbankReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository: _Repository = RaiffeisenbankReconciliationRepository(session)

    async def reconcile(
        self, *, command: ReconcileRaiffeisenbankJobCommand
    ) -> RaiffeisenbankReconciliationResult:
        """Write/replay only pairs anchored by the current running job.

        The method owns one atomic transaction.  It neither publishes pairs nor
        changes transaction classifications; readers remain unchanged until a
        later workflow stage owns publication.
        """
        try:
            (
                current_job,
                evidence_rows,
            ) = await self.repository.load_current_and_completed_evidence_for_update(
                current_job_id=_identifier(command.job_id),
                user_id=_identifier(command.user_id),
            )
            # AsyncSession expires ORM state on commit.  Preserve the scalar
            # result identity before the writer-owned commit so returning a
            # successful reconciliation never triggers implicit async I/O.
            result_job_id = current_job.id
            by_transaction = _one_evidence_per_transaction(evidence_rows)
            account_ids = tuple(sorted({row.batch.account_id for row in by_transaction.values()}))
            accounts, members = await self.repository.lock_accounts_and_members(
                account_ids=account_ids,
                user_id=command.user_id,
            )
            reconciliation_accounts = _reconciliation_accounts(
                accounts=accounts,
                members=members,
                account_ids=account_ids,
                user_id=command.user_id,
            )
            candidates = _candidates(by_transaction.values())
            _validate_credit_card_occurrences_needed(
                by_transaction=by_transaction,
                occurrences=await self.repository.load_occurrences_for_update(
                    representative_row_ids=tuple(
                        sorted(
                            row.row.id
                            for row in by_transaction.values()
                            if row.batch.account_id
                            in {
                                account.account_id
                                for account in reconciliation_accounts
                                if account.account_type.value == "credit_card"
                            }
                        )
                    )
                ),
                allow_link=True,
            )
            plan = plan_raiffeisenbank_reconciliation(
                accounts=reconciliation_accounts,
                candidates=candidates,
            )
            existing_pairs = await self.repository.load_pairs_for_update(
                transaction_ids=tuple(sorted(by_transaction)),
            )
            planned_by_id = {pair.pair_id: pair for pair in plan.pairs}
            _validate_existing_pairs(
                pairs=existing_pairs,
                planned_by_id=planned_by_id,
                transaction_ids=set(by_transaction),
                current_job_id=current_job.id,
            )

            created = replayed = 0
            affected: set[str] = set()
            existing_by_id = {pair.id: pair for pair in existing_pairs}
            for pair_plan in plan.pairs:
                current_leg = any(
                    current_job.id in by_transaction[transaction_id].job_ids
                    for transaction_id in (
                        pair_plan.from_transaction_id,
                        pair_plan.to_transaction_id,
                    )
                )
                existing = existing_by_id.get(pair_plan.pair_id)
                if existing is not None:
                    replayed += 1
                    if current_leg:
                        affected.update(
                            {
                                current_job.account_id,
                                by_transaction[pair_plan.from_transaction_id].batch.account_id,
                                by_transaction[pair_plan.to_transaction_id].batch.account_id,
                            }
                        )
                    continue
                if not current_leg:
                    # Historical-historical plans are validation only.  They
                    # must never be newly attributed to the current job.
                    continue
                self.repository.add_pair(
                    TransactionPairModel(
                        id=pair_plan.pair_id,
                        from_transaction_id=pair_plan.from_transaction_id,
                        to_transaction_id=pair_plan.to_transaction_id,
                        classification=pair_plan.classification,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=RECONCILIATION_EVIDENCE_VERSION,
                        evidence_hash=pair_plan.evidence_hash,
                        background_job_id=current_job.id,
                        published_at=None,
                        created_at=command.created_at,
                    )
                )
                created += 1
                affected.update(
                    {
                        current_job.account_id,
                        by_transaction[pair_plan.from_transaction_id].batch.account_id,
                        by_transaction[pair_plan.to_transaction_id].batch.account_id,
                    }
                )
            for account_id in sorted(affected):
                existing = await self.repository.get_affected_account_for_update(
                    job_id=current_job.id,
                    account_id=account_id,
                )
                if existing is None:
                    self.repository.add_affected_account(
                        ImportJobAffectedAccountModel(
                            job_id=current_job.id,
                            account_id=account_id,
                            user_id=command.user_id,
                            created_at=command.created_at,
                        )
                    )
                elif existing.user_id != command.user_id:
                    raise _fail()
            await self.repository.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return RaiffeisenbankReconciliationResult(
            job_id=result_job_id,
            pair_ids=tuple(sorted(planned_by_id)),
            pairs_created=created,
            pairs_replayed=replayed,
            affected_account_ids=tuple(sorted(affected)),
        )


async def validate_raiffeisenbank_publication_state(
    session: AsyncSession,
    *,
    job_id: str,
    user_id: str,
    affected_account_ids: tuple[str, ...],
    persisted_pairs: tuple[TransactionPairModel, ...],
) -> None:
    """Rebuild the exact pure plan under completion locks before publication."""

    repository = RaiffeisenbankReconciliationRepository(session)
    try:
        (
            current_job,
            evidence_rows,
        ) = await repository.load_current_and_completed_evidence_for_update(
            current_job_id=_identifier(job_id),
            user_id=_identifier(user_id),
        )
        by_transaction = _one_evidence_per_transaction(evidence_rows)
        account_ids = tuple(sorted({row.batch.account_id for row in by_transaction.values()}))
        accounts, members = await repository.lock_accounts_and_members(
            account_ids=account_ids,
            user_id=user_id,
        )
        reconciliation_accounts = _reconciliation_accounts(
            accounts=accounts,
            members=members,
            account_ids=account_ids,
            user_id=user_id,
        )
        _validate_credit_card_occurrences_needed(
            by_transaction=by_transaction,
            occurrences=await repository.load_occurrences_for_update(
                representative_row_ids=tuple(
                    sorted(
                        row.row.id
                        for row in by_transaction.values()
                        if row.batch.account_id
                        in {
                            account.account_id
                            for account in reconciliation_accounts
                            if account.account_type.value == "credit_card"
                        }
                    )
                )
            ),
            allow_link=False,
        )
        plan = plan_raiffeisenbank_reconciliation(
            accounts=reconciliation_accounts,
            candidates=_candidates(by_transaction.values()),
        )
        all_pairs = await repository.load_pairs_for_update(
            transaction_ids=tuple(sorted(by_transaction)),
        )
        planned_by_id = {pair.pair_id: pair for pair in plan.pairs}
        _validate_existing_pairs(
            pairs=all_pairs,
            planned_by_id=planned_by_id,
            transaction_ids=set(by_transaction),
            current_job_id=current_job.id,
        )
        existing_by_id = {pair.id: pair for pair in all_pairs}
        expected_pair_ids: set[str] = set()
        expected_affected = {current_job.account_id}
        for pair_plan in plan.pairs:
            if not any(
                current_job.id in by_transaction[transaction_id].job_ids
                for transaction_id in (
                    pair_plan.from_transaction_id,
                    pair_plan.to_transaction_id,
                )
            ):
                continue
            persisted = existing_by_id.get(pair_plan.pair_id)
            if persisted is None or persisted.background_job_id != current_job.id:
                raise _fail()
            expected_pair_ids.add(pair_plan.pair_id)
            expected_affected.update(
                {
                    by_transaction[pair_plan.from_transaction_id].batch.account_id,
                    by_transaction[pair_plan.to_transaction_id].batch.account_id,
                }
            )
        if (
            {pair.id for pair in persisted_pairs} != expected_pair_ids
            or tuple(sorted(expected_affected)) != affected_account_ids
            or any(pair.background_job_id != current_job.id for pair in persisted_pairs)
        ):
            raise _fail()
    except RaiffeisenbankReconciliationStateError:
        raise
    except Exception as exc:
        raise _fail() from exc


@dataclass(frozen=True, slots=True)
class _Evidence:
    job_ids: frozenset[str]
    batch: ImportBatchModel
    row: ImportRowModel
    transaction: TransactionModel


def _fail() -> RaiffeisenbankReconciliationStateError:
    return RaiffeisenbankReconciliationStateError()


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _one_evidence_per_transaction(
    rows: tuple[RaiffeisenbankReconciliationEvidenceRow, ...],
) -> dict[str, _Evidence]:
    grouped: dict[str, list[RaiffeisenbankReconciliationEvidenceRow]] = defaultdict(list)
    for evidence in rows:
        grouped[evidence.transaction.id].append(evidence)
    result: dict[str, _Evidence] = {}
    for transaction_id, values in grouped.items():
        first = values[0]
        if any(
            value.batch.id != first.batch.id
            or value.row.id != first.row.id
            or value.transaction.account_id != first.transaction.account_id
            for value in values[1:]
        ):
            raise _fail()
        result[transaction_id] = _Evidence(
            job_ids=frozenset(value.job.id for value in values),
            batch=first.batch,
            row=first.row,
            transaction=first.transaction,
        )
    return result


def _reconciliation_accounts(*, accounts, members, account_ids, user_id):
    account_by_id = {account.id: account for account in accounts}
    member_by_account = {member.account_id: member for member in members}
    if set(account_by_id) != set(account_ids) or set(member_by_account) != set(account_ids):
        raise _fail()
    if any(
        member.user_id != user_id
        or member.relation_type not in {AccountRelationType.owner, AccountRelationType.joint_owner}
        for member in member_by_account.values()
    ):
        raise _fail()
    return tuple(
        RaiffeisenbankReconciliationAccount(
            account_id=account_id,
            owner_id=user_id,
            account_type=account_by_id[account_id].type,
            currency=account_by_id[account_id].currency,
        )
        for account_id in account_ids
    )


def _candidates(values):
    candidates = []
    for evidence in values:
        row = evidence.row
        transaction = evidence.transaction
        if (
            row.status is not ImportRowStatus.imported
            or not isinstance(row.raw_data, dict)
            or not isinstance(row.normalized_data, dict)
            or transaction.import_batch_id != row.import_batch_id
            or transaction.account_id != evidence.batch.account_id
        ):
            raise _fail()
        candidates.append(
            RaiffeisenbankReconciliationCandidate(
                posted=RaiffeisenbankPostedTransactionIdentity(
                    transaction_id=transaction.id,
                    account_id=transaction.account_id,
                    date=transaction.date,
                    amount=transaction.amount,
                    currency=transaction.currency,
                    transaction_type=transaction.type,
                    classification=transaction.classification,
                    external_id=transaction.external_id,
                ),
                raw_data=row.raw_data,
            )
        )
    return tuple(candidates)


def _validate_credit_card_occurrences_needed(
    *, by_transaction, occurrences, allow_link: bool
) -> None:
    """Link every posted card representative to its durable RB-2 occurrence."""
    occurrence_by_row_id = {
        occurrence.representative_import_row_id: occurrence for occurrence in occurrences
    }
    for evidence in by_transaction.values():
        # Only rows whose immutable source evidence says card_statement must
        # have occurrence backing; normalizer/planner independently checks it.
        raw = evidence.row.raw_data
        if raw.get("__raiffeisenbank_statement_kind") != "card_statement":
            continue
        occurrence = occurrence_by_row_id.get(evidence.row.id)
        if (
            occurrence is None
            or occurrence.account_id != evidence.batch.account_id
            or occurrence.source is not ImportSource.raiffeisenbank
            or occurrence.canonical_transaction_id
            not in ({None, evidence.transaction.id} if allow_link else {evidence.transaction.id})
        ):
            raise _fail()
        if allow_link and occurrence.canonical_transaction_id is None:
            occurrence.canonical_transaction_id = evidence.transaction.id


def _validate_existing_pairs(*, pairs, planned_by_id, transaction_ids, current_job_id) -> None:
    for pair in pairs:
        if (
            pair.id not in planned_by_id
            or pair.classification is None
            or pair.source is not ImportSource.raiffeisenbank
            or pair.evidence_version != RECONCILIATION_EVIDENCE_VERSION
            or pair.evidence_hash != planned_by_id[pair.id].evidence_hash
        ):
            raise _fail()
        planned = planned_by_id[pair.id]
        if (
            pair.from_transaction_id != planned.from_transaction_id
            or pair.to_transaction_id != planned.to_transaction_id
        ):
            raise _fail()
        if pair.published_at is None and pair.background_job_id != current_job_id:
            raise _fail()
        if (
            pair.from_transaction_id not in transaction_ids
            or pair.to_transaction_id not in transaction_ids
        ):
            raise _fail()
