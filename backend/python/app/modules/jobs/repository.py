from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.transactions import (
    TransactionModel,
    TransactionPairModel,
    TransactionReportingEvidenceModel,
)
from app.db.models.users import UserModel
from app.modules.jobs.lifecycle import MAX_MANUAL_RETRIES, LeaseIdentity
from app.modules.jobs.models import ImportJobPayload


@dataclass(frozen=True, slots=True)
class EnqueuedBackgroundJob:
    job: BackgroundJobModel
    created: bool


@dataclass(frozen=True, slots=True)
class ClaimedBackgroundJob:
    job: BackgroundJobModel
    lease: LeaseIdentity


@dataclass(frozen=True, slots=True)
class ManualRetryBackgroundJob:
    job: BackgroundJobModel
    retried: bool


class BackgroundJobLeaseLostError(RuntimeError):
    """A stale worker attempted to mutate a lease it no longer owns."""


class BackgroundJobPublicationStaleError(RuntimeError):
    """Anchors no longer prove a publishable canonical state; retry safely."""


class BackgroundJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue_import_job(
        self,
        *,
        user_id: str,
        account_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        checkpoint: dict[str, Any],
        progress: dict[str, Any],
        max_attempts: int,
        now: datetime,
    ) -> EnqueuedBackgroundJob:
        values = {
            "id": str(uuid4()),
            "user_id": user_id,
            "account_id": account_id,
            "kind": BackgroundJobKind.import_workflow,
            "status": BackgroundJobStatus.queued,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "checkpoint": checkpoint,
            "progress": progress,
            "result": None,
            "error_code": None,
            "error_message": None,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "manual_retry_count": 0,
            "run_after": now,
            "lease_owner": None,
            "lease_version": 0,
            "lease_expires_at": None,
            "lease_heartbeat_at": None,
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        }
        statement = (
            insert(BackgroundJobModel)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=("userId", "accountId", "kind", "idempotencyKey")
            )
            .returning(BackgroundJobModel)
        )
        created = (await self.session.scalars(statement)).one_or_none()
        if created is not None:
            return EnqueuedBackgroundJob(job=created, created=True)
        replay = await self.get_owned_by_key(
            user_id=user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
        )
        if replay is None:
            raise RuntimeError("The canonical background job replay is missing.")
        return EnqueuedBackgroundJob(job=replay, created=False)

    async def reconcile_import_job_manifest(
        self,
        *,
        job: BackgroundJobModel,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
        now: datetime,
        create_if_missing: bool,
    ) -> None:
        """Create or exactly replay the immutable ImportJobBatch manifest.

        The caller owns the account and input-batch locks.  This method never
        widens a manifest: an existing row set must equal the canonical job
        payload before the enclosing enqueue transaction can commit.
        """
        if (
            job.user_id != user_id
            or job.account_id != account_id
            or job.kind is not BackgroundJobKind.import_workflow
        ):
            raise RuntimeError("The import-job manifest scope is invalid.")
        rows = tuple(
            (
                await self.session.scalars(
                    select(ImportJobBatchModel)
                    .where(ImportJobBatchModel.job_id == job.id)
                    .order_by(ImportJobBatchModel.batch_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if rows:
            if tuple(row.batch_id for row in rows) != batch_ids or any(
                row.user_id != user_id or row.account_id != account_id for row in rows
            ):
                raise RuntimeError("The import-job manifest does not match replay.")
        else:
            if not create_if_missing:
                raise RuntimeError("The import-job manifest is missing on replay.")
            for batch_id in batch_ids:
                self.session.add(
                    ImportJobBatchModel(
                        job_id=job.id,
                        batch_id=batch_id,
                        user_id=user_id,
                        account_id=account_id,
                        created_at=now,
                    )
                )
        initiator = await self.session.scalar(
            select(ImportJobAffectedAccountModel)
            .where(
                ImportJobAffectedAccountModel.job_id == job.id,
                ImportJobAffectedAccountModel.account_id == account_id,
            )
            .with_for_update()
        )
        if initiator is None:
            self.session.add(
                ImportJobAffectedAccountModel(
                    job_id=job.id,
                    account_id=account_id,
                    user_id=user_id,
                    created_at=now,
                )
            )
        elif initiator.user_id != user_id:
            raise RuntimeError("The import-job affected account scope is invalid.")
        await self.session.flush()

    async def get_owned_by_key(
        self,
        *,
        user_id: str,
        account_id: str,
        idempotency_key: str,
    ) -> BackgroundJobModel | None:
        return await self.session.scalar(
            select(BackgroundJobModel).where(
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.account_id == account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.idempotency_key == idempotency_key,
            )
        )

    async def get_owned(
        self,
        *,
        user_id: str,
        account_id: str,
        job_id: str,
        for_update: bool = False,
    ) -> BackgroundJobModel | None:
        statement = select(BackgroundJobModel).where(
            BackgroundJobModel.id == job_id,
            BackgroundJobModel.user_id == user_id,
            BackgroundJobModel.account_id == account_id,
            BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def find_owned_import_jobs_for_batch(
        self,
        *,
        user_id: str,
        account_id: str,
        batch_id: str,
    ) -> list[BackgroundJobModel]:
        """Return at most two scoped workflows containing one exact batch ID.

        The JSONB containment predicate deliberately targets the `batch_ids`
        array rather than text-searching an opaque payload.  Two rows are
        enough to distinguish the only valid cardinality (zero or one) from a
        corrupt duplicate state without loading an unbounded result.
        """

        # Registration already holds the account writer lock and exact batch
        # lock.  Do not lock BackgroundJob here: completion owns the inverse
        # Job -> publication targets -> Account order, and this is a
        # read-only recovery decision where a concurrent status transition may
        # safely resolve to either a safe resume or a safe conflict.
        result = await self.session.scalars(
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.account_id == account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.payload["batch_ids"].contains([batch_id]),
            )
            .order_by(BackgroundJobModel.created_at, BackgroundJobModel.id)
            .limit(2)
        )
        return list(result.all())

    async def retry_failed(
        self,
        *,
        user_id: str,
        account_id: str,
        job_id: str,
        now: datetime,
    ) -> ManualRetryBackgroundJob | None:
        job = await self.get_owned(
            user_id=user_id, account_id=account_id, job_id=job_id, for_update=True
        )
        if job is None:
            return None
        if (
            job.status is not BackgroundJobStatus.failed
            or job.manual_retry_count >= MAX_MANUAL_RETRIES
        ):
            return ManualRetryBackgroundJob(job=job, retried=False)
        job.status = BackgroundJobStatus.queued
        job.attempt_count = 0
        job.manual_retry_count += 1
        job.run_after = now
        job.result = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.lease_heartbeat_at = None
        job.started_at = None
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        return ManualRetryBackgroundJob(job=job, retried=True)

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimedBackgroundJob | None:
        if (
            not worker_id
            or worker_id != worker_id.strip()
            or len(worker_id) > 200
            or now.tzinfo is not None
            or lease_duration <= timedelta(0)
            or lease_duration > timedelta(minutes=30)
        ):
            raise ValueError("The background job claim boundary is invalid.")

        await self.session.execute(
            update(BackgroundJobModel)
            .where(
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.lease_expires_at <= now,
                BackgroundJobModel.attempt_count >= BackgroundJobModel.max_attempts,
            )
            .values(
                status=BackgroundJobStatus.failed,
                result=None,
                error_code="background_job_attempts_exhausted",
                error_message="Background processing could not be completed after all retries.",
                lease_owner=None,
                lease_expires_at=None,
                lease_heartbeat_at=None,
                finished_at=now,
                updated_at=now,
            )
        )

        candidate = BackgroundJobModel
        other = BackgroundJobModel.__table__.alias("other_running_job")
        other_running = exists(
            select(1)
            .select_from(other)
            .where(
                other.c.accountId == candidate.account_id,
                other.c.status == BackgroundJobStatus.running,
                other.c.id != candidate.id,
            )
        )
        ready = (
            select(candidate)
            .where(
                candidate.attempt_count < candidate.max_attempts,
                or_(
                    (
                        (candidate.status == BackgroundJobStatus.running)
                        & (candidate.lease_expires_at <= now)
                    ),
                    (
                        candidate.status.in_(
                            (BackgroundJobStatus.queued, BackgroundJobStatus.retry_wait)
                        )
                        & (candidate.run_after <= now)
                        & ~other_running
                    ),
                ),
            )
            .order_by(
                case((candidate.status == BackgroundJobStatus.running, 0), else_=1),
                candidate.run_after,
                candidate.created_at,
                candidate.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        job = await self.session.scalar(ready)
        if job is None:
            return None

        lock_scope = f"background-job-account:{job.account_id}"
        lock_id = int.from_bytes(sha256(lock_scope.encode()).digest()[:8], "big", signed=True)
        await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        conflicting = await self.session.scalar(
            select(BackgroundJobModel.id).where(
                BackgroundJobModel.account_id == job.account_id,
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.id != job.id,
            )
        )
        if conflicting is not None:
            return None

        job.status = BackgroundJobStatus.running
        job.lease_owner = worker_id
        job.lease_version += 1
        job.lease_expires_at = now + lease_duration
        job.lease_heartbeat_at = now
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        lease = LeaseIdentity(job_id=job.id, owner=worker_id, version=job.lease_version)
        return ClaimedBackgroundJob(job=job, lease=lease)

    async def heartbeat(
        self,
        *,
        lease: LeaseIdentity,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        if now.tzinfo is not None or not timedelta(0) < lease_duration <= timedelta(minutes=30):
            raise ValueError("The heartbeat boundary is invalid.")
        await self._fenced_update(
            lease,
            values={
                "lease_expires_at": now + lease_duration,
                "lease_heartbeat_at": now,
                "updated_at": now,
            },
        )

    async def checkpoint(
        self,
        *,
        lease: LeaseIdentity,
        checkpoint: dict[str, Any],
        progress: dict[str, Any],
        now: datetime,
    ) -> None:
        if now.tzinfo is not None:
            raise ValueError("The checkpoint timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={"checkpoint": checkpoint, "progress": progress, "updated_at": now},
        )

    async def complete(
        self,
        *,
        lease: LeaseIdentity,
        result: dict[str, Any],
        progress: dict[str, Any],
        now: datetime,
    ) -> None:
        if now.tzinfo is not None:
            raise ValueError("The completion timestamp is invalid.")
        job = await self.session.scalar(
            select(BackgroundJobModel)
            .where(BackgroundJobModel.id == lease.job_id)
            .with_for_update()
        )
        if (
            job is None
            or job.status is not BackgroundJobStatus.running
            or job.lease_owner != lease.owner
            or job.lease_version != lease.version
        ):
            raise BackgroundJobLeaseLostError("The background job is no longer owned.")
        affected_rows = tuple(
            (
                await self.session.scalars(
                    select(ImportJobAffectedAccountModel)
                    .where(ImportJobAffectedAccountModel.job_id == lease.job_id)
                    .order_by(ImportJobAffectedAccountModel.account_id)
                    .with_for_update()
                )
            ).all()
        )
        affected_account_ids = (
            tuple(row.account_id for row in affected_rows) if affected_rows else (job.account_id,)
        )
        if (
            job.account_id not in affected_account_ids
            or len(set(affected_account_ids)) != len(affected_account_ids)
            or any(row.user_id != job.user_id for row in affected_rows)
        ):
            raise BackgroundJobLeaseLostError("The import affected-account manifest is invalid.")
        accounts = tuple(
            (
                await self.session.scalars(
                    select(AccountModel)
                    .where(AccountModel.id.in_(affected_account_ids))
                    .order_by(AccountModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if tuple(account.id for account in accounts) != affected_account_ids:
            raise BackgroundJobLeaseLostError("An import publication account was removed.")
        targets = tuple(
            (
                await self.session.scalars(
                    select(ImportJobPublicationTargetModel)
                    .where(ImportJobPublicationTargetModel.job_id == lease.job_id)
                    .order_by(ImportJobPublicationTargetModel.user_id)
                    .with_for_update()
                )
            ).all()
        )
        # Every BackgroundJob is an import workflow.  A terminal transition is
        # therefore also the publication boundary: without durable targets, it
        # would release the current-value fence without an immutable baseline.
        if not targets:
            raise BackgroundJobLeaseLostError("The import publication targets are missing.")
        affected_memberships = set(
            (
                await self.session.execute(
                    select(
                        AccountMemberModel.account_id,
                        AccountMemberModel.user_id,
                    ).where(AccountMemberModel.account_id.in_(affected_account_ids))
                )
            ).all()
        )
        current_members = {user_id for _account_id, user_id in affected_memberships}
        anchor_pairs = set(
            (
                await self.session.execute(
                    select(
                        DailySnapshotBaselineModel.user_id,
                        DailySnapshotBaselineModel.timestamp,
                    ).where(
                        DailySnapshotBaselineModel.background_job_id == lease.job_id,
                        DailySnapshotBaselineModel.granularity == SnapshotGranularity.minute,
                        DailySnapshotBaselineModel.source == SnapshotSource.import_event,
                    )
                )
            ).all()
        )
        expected_anchors = {(target.user_id, target.bucket) for target in targets}
        if (
            {target.user_id for target in targets} != current_members
            or any(target.published_at is not None for target in targets)
            or anchor_pairs != expected_anchors
        ):
            raise BackgroundJobLeaseLostError("The import publication membership changed.")
        anchors = tuple(
            (
                await self.session.scalars(
                    select(DailySnapshotBaselineModel)
                    .where(DailySnapshotBaselineModel.background_job_id == lease.job_id)
                    .order_by(DailySnapshotBaselineModel.user_id)
                    .with_for_update()
                )
            ).all()
        )
        anchor_by_id = {anchor.id: anchor for anchor in anchors}
        anchor_by_user = {anchor.user_id: anchor for anchor in anchors}
        if len(anchor_by_id) != len(anchors) or len(anchor_by_user) != len(anchors):
            raise BackgroundJobLeaseLostError("The import publication anchors are invalid.")
        baseline_accounts = tuple(
            (
                await self.session.scalars(
                    select(DailySnapshotBaselineAccountModel)
                    .where(DailySnapshotBaselineAccountModel.baseline_id.in_(anchor_by_id))
                    .order_by(
                        DailySnapshotBaselineAccountModel.baseline_id,
                        DailySnapshotBaselineAccountModel.account_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        anchor_account_ids = tuple(sorted({item.account_id for item in baseline_accounts}))
        canonical_states = tuple(
            (
                await self.session.scalars(
                    select(AccountCanonicalStateModel)
                    .where(AccountCanonicalStateModel.account_id.in_(anchor_account_ids))
                    .order_by(AccountCanonicalStateModel.account_id)
                    .with_for_update()
                )
            ).all()
        )
        state_revisions = {state.account_id: state.last_revision for state in canonical_states}
        anchor_accounts_by_user: dict[str, set[str]] = {target.user_id: set() for target in targets}
        for item in baseline_accounts:
            anchor = anchor_by_id.get(item.baseline_id)
            if anchor is None or anchor.user_id not in anchor_accounts_by_user:
                raise BackgroundJobLeaseLostError("The import publication anchors are invalid.")
            anchor_accounts_by_user[anchor.user_id].add(item.account_id)
            if state_revisions.get(item.account_id) != item.canonical_revision:
                raise BackgroundJobPublicationStaleError(
                    "The import publication canonical state changed."
                )
        published_memberships = set(
            (
                await self.session.execute(
                    select(
                        AccountMemberModel.account_id,
                        AccountMemberModel.user_id,
                    ).where(AccountMemberModel.account_id.in_(anchor_account_ids))
                )
            ).all()
        )
        if any(
            (account_id, user_id) not in published_memberships
            for user_id, account_ids in anchor_accounts_by_user.items()
            for account_id in account_ids
        ) or any(
            not {
                account_id
                for account_id, member_user_id in affected_memberships
                if member_user_id == target.user_id
            }.issubset(anchor_accounts_by_user[target.user_id])
            for target in targets
        ):
            raise BackgroundJobLeaseLostError(
                "The import publication account lineage is incomplete."
            )
        if not set(affected_account_ids).issubset(state_revisions):
            raise BackgroundJobPublicationStaleError(
                "The import publication canonical state changed."
            )
        pairs = tuple(
            (
                await self.session.scalars(
                    select(TransactionPairModel)
                    .where(TransactionPairModel.background_job_id == lease.job_id)
                    .with_for_update()
                )
            ).all()
        )
        reporting_evidence = tuple(
            (
                await self.session.scalars(
                    select(TransactionReportingEvidenceModel)
                    .where(TransactionReportingEvidenceModel.background_job_id == lease.job_id)
                    .with_for_update()
                )
            ).all()
        )
        if any(item.published_at is not None for item in pairs) or any(
            item.published_at is not None for item in reporting_evidence
        ):
            raise BackgroundJobLeaseLostError(
                "Import reconciliation evidence is already published."
            )
        manifested = tuple(
            (
                await self.session.execute(
                    select(ImportJobBatchModel, ImportBatchModel)
                    .join(ImportBatchModel, ImportBatchModel.id == ImportJobBatchModel.batch_id)
                    .where(
                        ImportJobBatchModel.job_id == lease.job_id,
                        ImportJobBatchModel.user_id == job.user_id,
                    )
                    .order_by(ImportJobBatchModel.batch_id)
                    .with_for_update()
                )
            ).tuples()
        )
        try:
            payload_batch_ids = ImportJobPayload.model_validate(job.payload).batch_ids
        except ValueError as exc:
            raise BackgroundJobLeaseLostError("The import job payload is invalid.") from exc
        if (
            not manifested
            or tuple(membership.batch_id for membership, _batch in manifested) != payload_batch_ids
            or any(
                membership.account_id != job.account_id
                or membership.account_id != batch.account_id
                or membership.batch_id != batch.id
                or batch.user_id != job.user_id
                for membership, batch in manifested
            )
            or len({batch.source for _membership, batch in manifested}) != 1
        ):
            raise BackgroundJobLeaseLostError("The import batch manifest is invalid.")
        source = manifested[0][1].source
        batch_ids = tuple(membership.batch_id for membership, _batch in manifested)
        transactions = tuple(
            (
                await self.session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.import_batch_id.in_(batch_ids))
                    .order_by(TransactionModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if source is ImportSource.raiffeisenbank:
            from app.modules.imports.raiffeisenbank_reconciliation_service import (
                RaiffeisenbankReconciliationStateError,
                validate_raiffeisenbank_publication_state,
            )

            try:
                await validate_raiffeisenbank_publication_state(
                    self.session,
                    job_id=job.id,
                    user_id=job.user_id,
                    affected_account_ids=affected_account_ids,
                    persisted_pairs=pairs,
                )
                await self._validate_raiffeisenbank_reporting_evidence(
                    job=job,
                    transactions=transactions,
                    reporting_evidence=reporting_evidence,
                )
            except RaiffeisenbankReconciliationStateError as exc:
                raise BackgroundJobPublicationStaleError(
                    "The import reconciliation evidence changed."
                ) from exc
        elif pairs or reporting_evidence:
            raise BackgroundJobPublicationStaleError(
                "Unexpected reconciliation evidence cannot be published."
            )
        for target in targets:
            target.published_at = now
        for pair in pairs:
            pair.published_at = now
        for evidence in reporting_evidence:
            evidence.published_at = now
        await self.session.flush()
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.completed,
                "result": result,
                "progress": progress,
                "error_code": None,
                "error_message": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "finished_at": now,
                "updated_at": now,
            },
        )

    async def _validate_raiffeisenbank_reporting_evidence(
        self,
        *,
        job: BackgroundJobModel,
        transactions: tuple[TransactionModel, ...],
        reporting_evidence: tuple[TransactionReportingEvidenceModel, ...],
    ) -> None:
        from app.modules.fx.models import ExchangeRateObservation
        from app.modules.fx.validation import (
            ExchangeRateObservationValidationError,
            validate_exchange_rate_observation,
        )
        from app.modules.imports.raiffeisenbank_reporting_fx import (
            REPORTING_FX_CALCULATION_VERSION,
            RaiffeisenbankReportingFxStateError,
            calculate_reporting_amount,
        )
        from app.modules.market_data.models import ExchangeRateRequirement
        from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
        from app.modules.market_data.writer import exchange_rate_id

        user = await self.session.get(UserModel, job.user_id)
        if user is None:
            raise BackgroundJobPublicationStaleError("The reporting-currency owner was removed.")
        foreign = {
            transaction.id: transaction
            for transaction in transactions
            if transaction.currency != user.base_currency
        }
        evidence_by_transaction = {
            evidence.transaction_id: evidence for evidence in reporting_evidence
        }
        if len(evidence_by_transaction) != len(reporting_evidence) or set(
            evidence_by_transaction
        ) != set(foreign):
            raise BackgroundJobPublicationStaleError("The reporting-currency evidence set changed.")
        rate_ids = tuple(sorted({item.exchange_rate_id for item in reporting_evidence}))
        rates = tuple(
            (
                await self.session.scalars(
                    select(ExchangeRateModel)
                    .where(ExchangeRateModel.id.in_(rate_ids))
                    .order_by(ExchangeRateModel.id)
                    .with_for_update()
                )
            ).all()
        )
        rates_by_id = {rate.id: rate for rate in rates}
        if len(rates_by_id) != len(rate_ids):
            raise BackgroundJobPublicationStaleError("The reporting-currency FX lineage changed.")
        for transaction_id, transaction in foreign.items():
            evidence = evidence_by_transaction[transaction_id]
            rate = rates_by_id.get(evidence.exchange_rate_id)
            try:
                observation = (
                    validate_exchange_rate_observation(
                        ExchangeRateObservation(
                            from_currency=rate.from_currency,
                            to_currency=rate.to_currency,
                            provider=rate.source,
                            rate=rate.rate,
                            effective_at=rate.date,
                        ),
                        requirement=ExchangeRateRequirement(
                            from_currency=transaction.currency,
                            to_currency=user.base_currency,
                            through=transaction.date,
                            provider=rate.source,
                        ),
                        policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                    )
                    if rate is not None
                    else None
                )
                calculated = (
                    calculate_reporting_amount(transaction.amount, observation.rate)
                    if observation is not None
                    else None
                )
            except (
                ExchangeRateObservationValidationError,
                RaiffeisenbankReportingFxStateError,
            ) as exc:
                raise BackgroundJobPublicationStaleError(
                    "The reporting-currency calculation changed."
                ) from exc
            if (
                rate is None
                or evidence.background_job_id != job.id
                or evidence.calculation_version != REPORTING_FX_CALCULATION_VERSION
                or evidence.source_amount != transaction.amount
                or evidence.source_currency != transaction.currency
                or evidence.source_event_time != transaction.date
                or evidence.reporting_currency != user.base_currency
                or evidence.reporting_amount != calculated
                or transaction.reporting_amount != evidence.reporting_amount
                or transaction.reporting_currency != evidence.reporting_currency
                or rate.from_currency != evidence.source_currency
                or rate.to_currency != evidence.reporting_currency
                or observation is None
                or exchange_rate_id(observation) != rate.id
            ):
                raise BackgroundJobPublicationStaleError("The reporting-currency evidence changed.")
        if any(
            transaction.reporting_amount is not None or transaction.reporting_currency is not None
            for transaction in transactions
            if transaction.id not in foreign
        ):
            raise BackgroundJobPublicationStaleError(
                "Same-currency transactions contain unexpected reporting evidence."
            )

    async def schedule_retry(
        self,
        *,
        lease: LeaseIdentity,
        run_after: datetime,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> None:
        self._validate_safe_error(error_code, error_message)
        if now.tzinfo is not None or run_after.tzinfo is not None or run_after <= now:
            raise ValueError("The retry timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.retry_wait,
                "run_after": run_after,
                "error_code": error_code,
                "error_message": error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def fail(
        self,
        *,
        lease: LeaseIdentity,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> None:
        self._validate_safe_error(error_code, error_message)
        if now.tzinfo is not None:
            raise ValueError("The failure timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.failed,
                "result": None,
                "error_code": error_code,
                "error_message": error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "finished_at": now,
                "updated_at": now,
            },
        )

    async def release(
        self,
        *,
        lease: LeaseIdentity,
        now: datetime,
        run_after: datetime | None = None,
    ) -> None:
        effective_run_after = run_after or now
        if (
            now.tzinfo is not None
            or effective_run_after.tzinfo is not None
            or effective_run_after < now
        ):
            raise ValueError("The release timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.queued,
                "run_after": effective_run_after,
                "attempt_count": BackgroundJobModel.attempt_count - 1,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def defer(
        self,
        *,
        lease: LeaseIdentity,
        run_after: datetime,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if now.tzinfo is not None or run_after.tzinfo is not None or run_after <= now:
            raise ValueError("The deferred publication timestamp is invalid.")
        if (error_code is None) is not (error_message is None):
            raise ValueError("The deferred safe error is invalid.")
        if error_code is not None and error_message is not None:
            self._validate_safe_error(error_code, error_message)
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.retry_wait,
                "run_after": run_after,
                "attempt_count": BackgroundJobModel.attempt_count - 1,
                "error_code": error_code,
                "error_message": error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def _fenced_update(
        self,
        lease: LeaseIdentity,
        *,
        values: dict[str, Any],
    ) -> None:
        statement = (
            update(BackgroundJobModel)
            .where(
                BackgroundJobModel.id == lease.job_id,
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.lease_owner == lease.owner,
                BackgroundJobModel.lease_version == lease.version,
            )
            .values(**values)
        )
        result = cast(CursorResult[Any], await self.session.execute(statement))
        if result.rowcount != 1:
            raise BackgroundJobLeaseLostError("The background job lease is no longer owned.")

    @staticmethod
    def _validate_safe_error(code: str, message: str) -> None:
        if (
            not code
            or code != code.strip()
            or len(code) > 100
            or not message
            or message != message.strip()
            or len(message) > 1000
            or "\n" in code
            or "\r" in code
            or "\n" in message
            or "\r" in message
        ):
            raise ValueError("The public background job error is invalid.")
