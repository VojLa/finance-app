from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.models import (
    AccountMemberModel,
    AccountModel,
    AccountType,
    BackgroundJobKind,
    BackgroundJobModel,
    BackgroundJobStatus,
    UserModel,
)
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.url import normalize_database_url
from app.modules.jobs import worker as worker_module
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResult,
)
from app.modules.jobs.repository import (
    BackgroundJobLeaseLostError,
    BackgroundJobRepository,
    ClaimedBackgroundJob,
)
from app.modules.jobs.worker import (
    BackgroundJobWorker,
    CheckpointCallback,
    RetryableBackgroundJobError,
)

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2030, 1, 1, 12, 0, 0)
LEASE = timedelta(minutes=5)


def _job(
    job_id: str,
    user_id: str,
    account_id: str,
    *,
    run_after: datetime,
    max_attempts: int = 5,
) -> dict[str, object]:
    return {
        "id": job_id,
        "user_id": user_id,
        "account_id": account_id,
        "kind": BackgroundJobKind.import_workflow,
        "status": BackgroundJobStatus.queued,
        "idempotency_key": job_id,
        "payload": {"schema_version": 1, "batch_ids": [f"batch-{job_id}"]},
        "checkpoint": {"schema_version": 1, "phase": "queued", "completed_batch_ids": []},
        "progress": {
            "schema_version": 1,
            "phase": "queued",
            "completed_units": 0,
            "total_units": 7,
            "completed_batches": 0,
            "total_batches": 1,
        },
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempt_count": 0,
        "manual_retry_count": 0,
        "max_attempts": max_attempts,
        "run_after": run_after,
        "lease_owner": None,
        "lease_version": 0,
        "lease_expires_at": None,
        "lease_heartbeat_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _result(job_id: str) -> ImportJobResult:
    return ImportJobResult(
        batch_ids=(f"batch-{job_id}",),
        rows_total=1,
        rows_imported=1,
        rows_skipped=0,
        snapshot_refresh_status="created",
        completed_at=NOW,
    )


async def _seed_completion_publication_contract(
    engine: AsyncEngine,
    *,
    user_id: str,
    account_id: str,
    job_id: str,
) -> None:
    """Seed the durable target and minute import anchor required for completion."""
    async with engine.begin() as connection:
        snapshot_id = f"worker-net-worth-{job_id}"
        account_snapshot_id = f"worker-account-{job_id}"
        baseline_id = f"worker-baseline-{job_id}"
        state = (
            await connection.execute(
                select(
                    AccountCanonicalStateModel.last_revision,
                    AccountCanonicalStateModel.last_investment_revision,
                    AccountCanonicalStateModel.holding_revision,
                ).where(AccountCanonicalStateModel.account_id == account_id)
            )
        ).one_or_none()
        investment_revision: int | None
        holding_revision: int | None
        if state is None:
            canonical_revision = 0
            investment_revision = 0
            holding_revision = 0
            await connection.execute(
                insert(AccountCanonicalStateModel).values(
                    account_id=account_id,
                    last_revision=canonical_revision,
                    last_investment_revision=investment_revision,
                    holding_revision=holding_revision,
                    updated_at=NOW,
                )
            )
        else:
            canonical_revision = state[0]
            holding_revision = state[2]
            investment_revision = state[1] if holding_revision is not None else None
        await connection.execute(
            insert(AccountMemberModel).values(
                id=f"worker-member-{job_id}",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await connection.execute(
            insert(ImportJobPublicationTargetModel).values(
                job_id=job_id,
                user_id=user_id,
                bucket=NOW,
                published_at=None,
            )
        )
        await connection.execute(
            insert(AccountSnapshotModel).values(
                id=account_snapshot_id,
                account_id=account_id,
                timestamp=NOW,
                granularity=SnapshotGranularity.minute,
                source=SnapshotSource.import_event,
                currency="CZK",
                cash_value=Decimal("0"),
                investment_value=Decimal("0"),
                investment_cost_basis=Decimal("0"),
                liabilities_value=Decimal("0"),
                total_value=Decimal("0"),
                is_recalculated=False,
                calculated_at=NOW,
                calculation_version=1,
                created_at=NOW,
                net_deposits_value=Decimal("0"),
                realized_pnl_value=Decimal("0"),
                unrealized_pnl_value=Decimal("0"),
                fees_value=Decimal("0"),
                taxes_value=Decimal("0"),
                cash_value_by_currency={},
                investment_value_by_currency={},
                investment_cost_basis_by_currency={},
                net_deposits_by_currency={},
                realized_pnl_by_currency={},
                unrealized_pnl_by_currency={},
                fees_by_currency={},
                taxes_by_currency={},
                exchange_rates={},
            )
        )
        await connection.execute(
            insert(AccountSnapshotCanonicalBoundaryModel).values(
                snapshot_id=account_snapshot_id,
                account_id=account_id,
                canonical_revision=canonical_revision,
                investment_revision=investment_revision,
                holding_revision=holding_revision,
                selected_liability_balance_id=None,
                created_at=NOW,
            )
        )
        await connection.execute(
            insert(NetWorthSnapshotModel).values(
                id=snapshot_id,
                user_id=user_id,
                timestamp=NOW,
                granularity=SnapshotGranularity.minute,
                source=SnapshotSource.import_event,
                currency="CZK",
                cash_value=Decimal("0"),
                portfolio_value=Decimal("0"),
                liabilities_value=Decimal("0"),
                total_net_worth=Decimal("0"),
                is_recalculated=False,
                calculated_at=NOW,
                calculation_version=1,
                created_at=NOW,
                cash_value_by_currency={},
                portfolio_value_by_currency={},
                liabilities_value_by_currency={},
                total_net_worth_by_currency={},
                exchange_rates={},
            )
        )
        await connection.execute(
            insert(DailySnapshotBaselineModel).values(
                id=baseline_id,
                user_id=user_id,
                net_worth_snapshot_id=snapshot_id,
                timestamp=NOW,
                granularity=SnapshotGranularity.minute,
                currency="CZK",
                calculation_version=1,
                source=SnapshotSource.import_event,
                created_at=NOW,
                background_job_id=job_id,
            )
        )
        await connection.execute(
            insert(DailySnapshotBaselineAccountModel).values(
                baseline_id=baseline_id,
                account_id=account_id,
                account_type=AccountType.bank,
                account_currency="CZK",
                primary_snapshot_id=account_snapshot_id,
                presentation_snapshot_id=account_snapshot_id,
                canonical_revision=canonical_revision,
                investment_revision=investment_revision,
                holding_revision=holding_revision,
                selected_liability_balance_id=None,
            )
        )


async def _cleanup_completion_publication_contract(
    engine: AsyncEngine,
    *,
    user_id: str,
    account_id: str,
    job_id: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(DailySnapshotBaselineModel).where(
                DailySnapshotBaselineModel.background_job_id == job_id
            )
        )
        await connection.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
        )
        await connection.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
        )
        await connection.execute(
            delete(ImportJobPublicationTargetModel).where(
                ImportJobPublicationTargetModel.job_id == job_id
            )
        )
        await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await connection.execute(delete(UserModel).where(UserModel.id == user_id))


class _CheckpointAwareCompletionExecutor:
    def __init__(self, expected_phase: ImportJobPhase) -> None:
        self.expected_phase = expected_phase
        self.executions = 0

    async def execute(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        checkpoint: CheckpointCallback,
    ) -> ImportJobResult:
        del checkpoint
        self.executions += 1
        persisted = ImportJobCheckpoint.model_validate(claimed.job.checkpoint)
        assert persisted.phase is self.expected_phase
        return _result(claimed.job.id)


class _RetryableExecutor:
    async def execute(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        checkpoint: CheckpointCallback,
    ) -> ImportJobResult:
        del claimed, checkpoint
        raise RetryableBackgroundJobError(
            code="snapshot_temporarily_unavailable",
            message="Snapshot evidence is temporarily unavailable.",
        )


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_claim_recovery_and_fencing_are_concurrency_safe() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_ids = [f"worker-user-a-{suffix}", f"worker-user-b-{suffix}"]
    account_ids = [f"worker-account-a-{suffix}", f"worker-account-b-{suffix}"]
    job_ids = [f"worker-job-a-{suffix}", f"worker-job-b-{suffix}"]
    try:
        async with engine.begin() as connection:
            for index in range(2):
                await connection.execute(
                    insert(UserModel).values(
                        id=user_ids[index],
                        email=f"{user_ids[index]}@example.test",
                        name="Worker test",
                        password_hash=None,
                        base_currency="CZK",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await connection.execute(
                    insert(AccountModel).values(
                        id=account_ids[index],
                        name="Worker account",
                        type=AccountType.bank,
                        currency="CZK",
                        color=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                        notes=None,
                    )
                )
                await connection.execute(
                    insert(BackgroundJobModel).values(
                        **_job(job_ids[index], user_ids[index], account_ids[index], run_after=NOW)
                    )
                )

        barrier = asyncio.Barrier(2)

        async def claim(worker: str):
            async with sessions() as session:
                await barrier.wait()
                claimed = await BackgroundJobRepository(session).claim_next(
                    worker_id=worker,
                    now=NOW,
                    lease_duration=LEASE,
                )
                await session.commit()
                return claimed

        claimed = await asyncio.gather(claim("worker-a"), claim("worker-b"))
        assert all(item is not None for item in claimed)
        assert {item.job.id for item in claimed if item is not None} == set(job_ids)
        first = next(item for item in claimed if item is not None and item.job.id == job_ids[0])
        stale_lease = first.lease

        async with sessions() as session:
            assert (
                await BackgroundJobRepository(session).claim_next(
                    worker_id="worker-c",
                    now=NOW + timedelta(minutes=1),
                    lease_duration=LEASE,
                )
                is None
            )
            await session.commit()

        async with sessions() as session:
            reclaimed = await BackgroundJobRepository(session).claim_next(
                worker_id="worker-recovery",
                now=NOW + timedelta(minutes=6),
                lease_duration=LEASE,
            )
            assert reclaimed is not None
            assert reclaimed.job.id in job_ids
            assert reclaimed.lease.version == 2
            await session.commit()

        async with sessions() as session:
            with pytest.raises(BackgroundJobLeaseLostError):
                await BackgroundJobRepository(session).checkpoint(
                    lease=stale_lease,
                    checkpoint={"schema_version": 1},
                    progress={"schema_version": 1},
                    now=NOW + timedelta(minutes=6),
                )
            await session.rollback()

        async with engine.connect() as connection:
            attempts = list(
                (
                    await connection.scalars(
                        select(BackgroundJobModel.attempt_count)
                        .where(BackgroundJobModel.id.in_(job_ids))
                        .order_by(BackgroundJobModel.id)
                    )
                ).all()
            )
            assert sorted(attempts) == [1, 2]
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            await connection.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_crashed_committed_checkpoint_is_reclaimed_and_completed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process can die after a durable stage checkpoint without losing its recovery point."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id, job_id = (
        f"checkpoint-user-{suffix}",
        f"checkpoint-account-{suffix}",
        f"checkpoint-job-{suffix}",
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Checkpoint recovery",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Checkpoint recovery",
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    notes=None,
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job(job_id, user_id, account_id, run_after=NOW)
                )
            )
        await _seed_completion_publication_contract(
            engine,
            user_id=user_id,
            account_id=account_id,
            job_id=job_id,
        )

        # This simulates a process dying after a stage has committed its durable
        # work but before the worker can run another stage or release its lease.
        async with sessions() as session:
            claimed = await BackgroundJobRepository(session).claim_next(
                worker_id="crashed-worker", now=NOW, lease_duration=LEASE
            )
            assert claimed is not None
            await BackgroundJobRepository(session).checkpoint(
                lease=claimed.lease,
                checkpoint=ImportJobCheckpoint(
                    phase=ImportJobPhase.parsing,
                    completed_batch_ids=(f"batch-{job_id}",),
                ).model_dump(mode="json"),
                progress=ImportJobProgress(
                    phase=ImportJobPhase.parsing,
                    completed_units=1,
                    total_units=7,
                    completed_batches=1,
                    total_batches=1,
                ).model_dump(mode="json"),
                now=NOW,
            )
            await session.commit()

        executor = _CheckpointAwareCompletionExecutor(ImportJobPhase.parsing)
        monkeypatch.setattr(worker_module, "_now", lambda: NOW + LEASE + timedelta(seconds=1))
        recovered = BackgroundJobWorker(
            sessions,
            executor,
            worker_id="recovery-worker",
            lease_duration=LEASE,
            heartbeat_interval=timedelta(seconds=1),
        )
        assert await recovered.run_once() is True
        assert executor.executions == 1

        async with engine.connect() as connection:
            completed = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.result,
                        BackgroundJobModel.error_code,
                        BackgroundJobModel.lease_owner,
                        BackgroundJobModel.lease_expires_at,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert completed == (
                BackgroundJobStatus.completed,
                2,
                _result(job_id).model_dump(mode="json"),
                None,
                None,
                None,
            )
    finally:
        await _cleanup_completion_publication_contract(
            engine,
            user_id=user_id,
            account_id=account_id,
            job_id=job_id,
        )
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_one_live_job_has_one_claim_and_completion_requires_publication_targets() -> None:
    """A lease alone can never publish an import without its durable baseline contract."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id, job_id = (
        f"fencing-user-{suffix}",
        f"fencing-account-{suffix}",
        f"fencing-job-{suffix}",
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Fencing",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Fencing",
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    notes=None,
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job(job_id, user_id, account_id, run_after=NOW)
                )
            )

        barrier = asyncio.Barrier(2)

        async def claim(worker_id: str) -> ClaimedBackgroundJob | None:
            async with sessions() as session:
                await barrier.wait()
                result = await BackgroundJobRepository(session).claim_next(
                    worker_id=worker_id,
                    now=NOW,
                    lease_duration=LEASE,
                )
                await session.commit()
                return result

        first, second = await asyncio.gather(claim("first-worker"), claim("second-worker"))
        claims = tuple(item for item in (first, second) if item is not None)
        assert len(claims) == 1
        stale_lease = claims[0].lease

        async with sessions() as session:
            reclaimed = await BackgroundJobRepository(session).claim_next(
                worker_id="reclaiming-worker",
                now=NOW + LEASE + timedelta(seconds=1),
                lease_duration=LEASE,
            )
            assert reclaimed is not None
            assert reclaimed.lease.version == stale_lease.version + 1
            await session.commit()

        stale_operations = (
            lambda repository: repository.heartbeat(
                lease=stale_lease,
                now=NOW + LEASE + timedelta(seconds=1),
                lease_duration=LEASE,
            ),
            lambda repository: repository.checkpoint(
                lease=stale_lease,
                checkpoint=ImportJobCheckpoint().model_dump(mode="json"),
                progress=ImportJobProgress(
                    phase=ImportJobPhase.queued,
                    completed_units=0,
                    total_units=7,
                    completed_batches=0,
                    total_batches=1,
                ).model_dump(mode="json"),
                now=NOW + LEASE + timedelta(seconds=1),
            ),
            lambda repository: repository.complete(
                lease=stale_lease,
                result=_result(job_id).model_dump(mode="json"),
                progress=ImportJobProgress(
                    phase=ImportJobPhase.completed,
                    completed_units=7,
                    total_units=7,
                    completed_batches=1,
                    total_batches=1,
                ).model_dump(mode="json"),
                now=NOW + LEASE + timedelta(seconds=1),
            ),
        )
        for operation in stale_operations:
            async with sessions() as session:
                with pytest.raises(BackgroundJobLeaseLostError):
                    await operation(BackgroundJobRepository(session))
                await session.rollback()

        async with sessions() as session:
            with pytest.raises(BackgroundJobLeaseLostError, match="targets are missing"):
                await BackgroundJobRepository(session).complete(
                    lease=reclaimed.lease,
                    result=_result(job_id).model_dump(mode="json"),
                    progress=ImportJobProgress(
                        phase=ImportJobPhase.completed,
                        completed_units=7,
                        total_units=7,
                        completed_batches=1,
                        total_batches=1,
                    ).model_dump(mode="json"),
                    now=NOW + LEASE + timedelta(seconds=2),
                )
            await session.rollback()
        async with engine.connect() as connection:
            published = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.result,
                        BackgroundJobModel.lease_owner,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert published == (
                BackgroundJobStatus.running,
                None,
                "reclaiming-worker",
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_retry_wait_exhaustion_and_manual_retry_keep_one_canonical_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient failures back off, exhaust safely, then manually resume the same job."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id, job_id = (
        f"retry-worker-user-{suffix}",
        f"retry-worker-account-{suffix}",
        f"retry-worker-job-{suffix}",
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Retry worker",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Retry worker",
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    notes=None,
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job(job_id, user_id, account_id, run_after=NOW, max_attempts=2)
                )
            )
        await _seed_completion_publication_contract(
            engine,
            user_id=user_id,
            account_id=account_id,
            job_id=job_id,
        )

        retrying = _RetryableExecutor()
        monkeypatch.setattr(worker_module, "_now", lambda: NOW)
        first_worker = BackgroundJobWorker(
            sessions,
            retrying,
            worker_id="retry-worker-a",
            lease_duration=LEASE,
            heartbeat_interval=timedelta(seconds=1),
        )
        assert await first_worker.run_once() is True
        async with engine.connect() as connection:
            waiting = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.run_after,
                        BackgroundJobModel.error_code,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert waiting == (
                BackgroundJobStatus.retry_wait,
                1,
                NOW + timedelta(seconds=5),
                "snapshot_temporarily_unavailable",
            )

        monkeypatch.setattr(worker_module, "_now", lambda: NOW + timedelta(seconds=5))
        second_worker = BackgroundJobWorker(
            sessions,
            retrying,
            worker_id="retry-worker-b",
            lease_duration=LEASE,
            heartbeat_interval=timedelta(seconds=1),
        )
        assert await second_worker.run_once() is True
        async with engine.connect() as connection:
            failed = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.error_code,
                        BackgroundJobModel.result,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert failed == (
                BackgroundJobStatus.failed,
                2,
                "background_job_attempts_exhausted",
                None,
            )

        async with sessions() as session:
            retried = await BackgroundJobRepository(session).retry_failed(
                user_id=user_id,
                account_id=account_id,
                job_id=job_id,
                now=NOW + timedelta(seconds=6),
            )
            assert retried is not None and retried.retried is True
            await session.commit()

        completing = _CheckpointAwareCompletionExecutor(ImportJobPhase.queued)
        monkeypatch.setattr(worker_module, "_now", lambda: NOW + timedelta(seconds=6))
        manual_worker = BackgroundJobWorker(
            sessions,
            completing,
            worker_id="manual-retry-worker",
            lease_duration=LEASE,
            heartbeat_interval=timedelta(seconds=1),
        )
        assert await manual_worker.run_once() is True
        assert completing.executions == 1
        async with engine.connect() as connection:
            completed = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.manual_retry_count,
                        BackgroundJobModel.result,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert completed == (
                BackgroundJobStatus.completed,
                1,
                1,
                _result(job_id).model_dump(mode="json"),
            )
    finally:
        await _cleanup_completion_publication_contract(
            engine,
            user_id=user_id,
            account_id=account_id,
            job_id=job_id,
        )
        await engine.dispose()
