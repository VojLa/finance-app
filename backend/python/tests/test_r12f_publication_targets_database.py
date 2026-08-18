"""PostgreSQL proof for immutable per-user import publication targets."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportSource,
    ImportStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state.service import CanonicalChangeKind, CanonicalStateService
from app.modules.imports.models import ImportBatchCreateRequest, ImportRegistrationResponse
from app.modules.imports.service import ImportBatchAlreadyImportedError
from app.modules.jobs.publication_service import ImportJobPublicationService
from app.modules.jobs.repository import (
    BackgroundJobLeaseLostError,
    BackgroundJobPublicationStaleError,
    BackgroundJobRepository,
    ClaimedBackgroundJob,
)
from app.modules.jobs.service import BackgroundJobService

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2034, 2, 3, 10, 15)
LEASE = timedelta(minutes=5)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _job(job_id: str, user_id: str, account_id: str) -> dict[str, object]:
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
        "max_attempts": 5,
        "run_after": NOW,
        "lease_owner": None,
        "lease_version": 0,
        "lease_expires_at": None,
        "lease_heartbeat_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _complete_progress() -> dict[str, object]:
    return {
        "schema_version": 1,
        "phase": "completed",
        "completed_units": 7,
        "total_units": 7,
        "completed_batches": 1,
        "total_batches": 1,
    }


async def _claim(
    sessions: async_sessionmaker,
    *,
    job_id: str,
    worker_id: str,
    now: datetime,
) -> ClaimedBackgroundJob:
    async with sessions() as session:
        claimed = await BackgroundJobRepository(session).claim_next(
            worker_id=worker_id,
            now=now,
            lease_duration=LEASE,
        )
        await session.commit()
    assert claimed is not None
    assert claimed.job.id == job_id
    return claimed


async def _insert_import_anchor(
    engine: AsyncEngine,
    *,
    job_id: str,
    user_id: str,
    account_id: str,
    bucket: datetime,
    suffix: str,
    canonical_revision: int = 0,
) -> None:
    async with engine.begin() as connection:
        snapshot_id = f"publication-net-worth-{suffix}"
        account_snapshot_id = f"publication-account-{account_id}-{bucket:%Y%m%d%H%M}"
        baseline_id = f"publication-baseline-{suffix}"
        state = await connection.scalar(
            select(AccountCanonicalStateModel).where(
                AccountCanonicalStateModel.account_id == account_id
            )
        )
        if state is None:
            await connection.execute(
                insert(AccountCanonicalStateModel).values(
                    account_id=account_id,
                    last_revision=canonical_revision,
                    last_investment_revision=canonical_revision,
                    holding_revision=canonical_revision,
                    updated_at=bucket,
                )
            )
        existing_account_snapshot = await connection.scalar(
            select(AccountSnapshotModel.id).where(
                AccountSnapshotModel.account_id == account_id,
                AccountSnapshotModel.timestamp == bucket,
                AccountSnapshotModel.currency == "CZK",
                AccountSnapshotModel.granularity == SnapshotGranularity.minute,
            )
        )
        if existing_account_snapshot is None:
            await connection.execute(
                insert(AccountSnapshotModel).values(
                    id=account_snapshot_id,
                    account_id=account_id,
                    timestamp=bucket,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.import_event,
                    currency="CZK",
                    cash_value=Decimal("0"),
                    investment_value=Decimal("0"),
                    investment_cost_basis=Decimal("0"),
                    liabilities_value=Decimal("0"),
                    total_value=Decimal("0"),
                    is_recalculated=False,
                    calculated_at=bucket,
                    calculation_version=1,
                    created_at=bucket,
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
                    investment_revision=canonical_revision,
                    holding_revision=canonical_revision,
                    selected_liability_balance_id=None,
                    created_at=bucket,
                )
            )
        else:
            account_snapshot_id = existing_account_snapshot
        await connection.execute(
            insert(NetWorthSnapshotModel).values(
                id=snapshot_id,
                user_id=user_id,
                timestamp=bucket,
                granularity=SnapshotGranularity.minute,
                source=SnapshotSource.import_event,
                currency="CZK",
                cash_value=Decimal("0"),
                portfolio_value=Decimal("0"),
                liabilities_value=Decimal("0"),
                total_net_worth=Decimal("0"),
                is_recalculated=False,
                calculated_at=bucket,
                calculation_version=1,
                created_at=bucket,
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
                timestamp=bucket,
                granularity=SnapshotGranularity.minute,
                currency="CZK",
                calculation_version=1,
                source=SnapshotSource.import_event,
                created_at=bucket,
                background_job_id=job_id,
            )
        )
        await connection.execute(
            insert(DailySnapshotBaselineAccountModel).values(
                baseline_id=baseline_id,
                account_id=account_id,
                account_type=AccountType.broker,
                account_currency="CZK",
                primary_snapshot_id=account_snapshot_id,
                presentation_snapshot_id=account_snapshot_id,
                canonical_revision=canonical_revision,
                investment_revision=canonical_revision,
                holding_revision=canonical_revision,
                selected_liability_balance_id=None,
            )
        )


async def _cleanup(
    engine: AsyncEngine,
    *,
    job_ids: tuple[str, ...],
    account_ids: tuple[str, ...],
    user_ids: tuple[str, ...],
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(DailySnapshotBaselineModel).where(
                DailySnapshotBaselineModel.background_job_id.in_(job_ids)
            )
        )
        await connection.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
        )
        await connection.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
        )
        await connection.execute(
            delete(ImportJobPublicationTargetModel).where(
                ImportJobPublicationTargetModel.job_id.in_(job_ids)
            )
        )
        await connection.execute(
            delete(BackgroundJobModel).where(BackgroundJobModel.id.in_(job_ids))
        )
        await connection.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await connection.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))


async def _seed_single_publication(
    engine: AsyncEngine,
    *,
    user_id: str,
    account_id: str,
    job_id: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(UserModel).values(
                id=user_id,
                email=f"{user_id}@example.test",
                name="Publication race test",
                password_hash=None,
                base_currency="CZK",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await connection.execute(
            insert(AccountModel).values(
                id=account_id,
                name="Publication race account",
                type=AccountType.broker,
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
            insert(AccountMemberModel).values(
                id=f"publication-member-{account_id}",
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
            insert(BackgroundJobModel).values(**_job(job_id, user_id, account_id))
        )


@pytest.mark.integration
async def test_registration_does_not_deadlock_with_completion_lock_boundary() -> None:
    """The recovery read may race completion without taking the job row lock.

    Completion owns Job -> targets -> Account.  Registration owns Account ->
    Batch, then performs only a scoped, bounded job read, so PostgreSQL can
    resolve the status race as either safe resume or terminal conflict without
    forming the inverse Account -> Batch -> Job wait cycle.
    """

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id = f"registration-owner-{suffix}"
    account_id = f"registration-account-{suffix}"
    job_id = f"registration-job-{suffix}"
    batch_id = f"batch-{job_id}"
    try:
        await _seed_single_publication(
            engine, user_id=user_id, account_id=account_id, job_id=job_id
        )
        async with engine.begin() as connection:
            await connection.execute(
                insert(ImportBatchModel).values(
                    id=batch_id,
                    user_id=user_id,
                    account_id=account_id,
                    source=ImportSource.trading212,
                    filename="completion-race.csv",
                    file_size=100,
                    file_encoding="utf-8",
                    checksum="a" * 64,
                    status=ImportStatus.completed,
                    rows_total=1,
                    rows_imported=1,
                    rows_skipped=0,
                    created_at=NOW,
                    completed_at=NOW,
                    retain_until=None,
                    raw_data_purged_at=None,
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
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=user_id,
            account_id=account_id,
            bucket=NOW,
            suffix=f"registration-{suffix}",
        )
        claimed = await _claim(sessions, job_id=job_id, worker_id="registration-race", now=NOW)

        async def complete() -> None:
            async with sessions() as session:
                await BackgroundJobRepository(session).complete(
                    lease=claimed.lease,
                    result={"published": True},
                    progress=_complete_progress(),
                    now=NOW + timedelta(seconds=1),
                )
                await session.commit()

        async def register() -> ImportRegistrationResponse | ImportBatchAlreadyImportedError:
            async with sessions() as session:
                try:
                    return await BackgroundJobService(session).register_import_batch(
                        principal=AuthenticatedPrincipal(
                            user_id=user_id, email=f"{user_id}@example.test"
                        ),
                        account_id=account_id,
                        payload=ImportBatchCreateRequest(
                            source=ImportSource.trading212,
                            filename="completion-race.csv",
                            file_size=100,
                            file_encoding="utf-8",
                            checksum="a" * 64,
                        ),
                    )
                except ImportBatchAlreadyImportedError as exc:
                    return exc

        _, registration = await asyncio.wait_for(asyncio.gather(complete(), register()), timeout=5)
        assert isinstance(registration, ImportBatchAlreadyImportedError) or (
            registration.status == "resume_job"
            and registration.batch is None
            and registration.job.id == job_id
        )
        if isinstance(registration, ImportBatchAlreadyImportedError):
            assert registration.code == "import_batch_already_imported"
        async with sessions() as session:
            job = await session.get(BackgroundJobModel, job_id)
            assert job is not None and job.status is BackgroundJobStatus.completed
        async with sessions() as session:
            with pytest.raises(ImportBatchAlreadyImportedError) as terminal:
                await BackgroundJobService(session).register_import_batch(
                    principal=AuthenticatedPrincipal(
                        user_id=user_id, email=f"{user_id}@example.test"
                    ),
                    account_id=account_id,
                    payload=ImportBatchCreateRequest(
                        source=ImportSource.trading212,
                        filename="completion-race.csv",
                        file_size=100,
                        file_encoding="utf-8",
                        checksum="a" * 64,
                    ),
                )
            assert terminal.value.code == "import_batch_already_imported"
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(ImportBatchModel).where(ImportBatchModel.id == batch_id)
            )
        await _cleanup(
            engine,
            job_ids=(job_id,),
            account_ids=(account_id,),
            user_ids=(user_id,),
        )
        await engine.dispose()


@pytest.mark.integration
async def test_shared_members_require_exact_targets_and_anchors_before_atomic_completion() -> None:
    """A shared account cannot release either member without both immutable anchors."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    owner_id, viewer_id = f"target-owner-{suffix}", f"target-viewer-{suffix}"
    shared_account_id, missing_account_id = f"target-shared-{suffix}", f"target-missing-{suffix}"
    job_id, missing_job_id = f"target-b-shared-{suffix}", f"target-a-missing-{suffix}"
    try:
        async with engine.begin() as connection:
            for user_id in (owner_id, viewer_id):
                await connection.execute(
                    insert(UserModel).values(
                        id=user_id,
                        email=f"{user_id}@example.test",
                        name="Publication target test",
                        password_hash=None,
                        base_currency="CZK",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            for account_id in (shared_account_id, missing_account_id):
                await connection.execute(
                    insert(AccountModel).values(
                        id=account_id,
                        name="Publication target account",
                        type=AccountType.broker,
                        currency="CZK",
                        color=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                        notes=None,
                    )
                )
            for member_id, account_id, user_id, role, relation in (
                (
                    f"owner-{suffix}",
                    shared_account_id,
                    owner_id,
                    AccountMemberRole.owner,
                    AccountRelationType.owner,
                ),
                (
                    f"viewer-{suffix}",
                    shared_account_id,
                    viewer_id,
                    AccountMemberRole.viewer,
                    AccountRelationType.collaborator,
                ),
                (
                    f"missing-owner-{suffix}",
                    missing_account_id,
                    owner_id,
                    AccountMemberRole.owner,
                    AccountRelationType.owner,
                ),
            ):
                await connection.execute(
                    insert(AccountMemberModel).values(
                        id=member_id,
                        account_id=account_id,
                        user_id=user_id,
                        role=role,
                        relation_type=relation,
                        invited_by_id=None,
                        accepted_at=NOW,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            await connection.execute(
                insert(BackgroundJobModel).values(**_job(job_id, owner_id, shared_account_id))
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job(missing_job_id, owner_id, missing_account_id)
                )
            )

        missing = await _claim(
            sessions, job_id=missing_job_id, worker_id="target-no-target", now=NOW
        )
        async with sessions() as session:
            with pytest.raises(BackgroundJobLeaseLostError, match="targets are missing"):
                await BackgroundJobRepository(session).complete(
                    lease=missing.lease,
                    result={"published": True},
                    progress=_complete_progress(),
                    now=NOW,
                )
            await session.rollback()

        claimed = await _claim(sessions, job_id=job_id, worker_id="target-shared", now=NOW)
        async with sessions() as session:
            targets = await ImportJobPublicationService(session).reserve(
                job_id=job_id,
                account_id=shared_account_id,
                requested_bucket=NOW,
            )
        assert targets == tuple(sorted(targets, key=lambda target: target.user_id))
        assert {(target.user_id, target.bucket) for target in targets} == {
            (owner_id, NOW),
            (viewer_id, NOW),
        }

        # Membership can change after reservation. A departed unpublished
        # target and its unpublished anchor are retired; completion then uses
        # exactly the current member set.
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=viewer_id,
            account_id=shared_account_id,
            bucket=NOW,
            suffix=f"viewer-{suffix}",
        )
        async with sessions() as session:
            await session.execute(
                delete(AccountMemberModel).where(
                    AccountMemberModel.account_id == shared_account_id,
                    AccountMemberModel.user_id == viewer_id,
                )
            )
            await session.commit()
        async with sessions() as session:
            reconciled = await ImportJobPublicationService(session).reserve(
                job_id=job_id,
                account_id=shared_account_id,
                requested_bucket=NOW,
            )
        assert reconciled == (reconciled[0],)
        assert reconciled[0].user_id == owner_id
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(DailySnapshotBaselineModel.id).where(
                        DailySnapshotBaselineModel.background_job_id == job_id,
                        DailySnapshotBaselineModel.user_id == viewer_id,
                    )
                )
                is None
            )
            assert (
                await connection.scalar(
                    select(ImportJobPublicationTargetModel.job_id).where(
                        ImportJobPublicationTargetModel.job_id == job_id,
                        ImportJobPublicationTargetModel.user_id == viewer_id,
                    )
                )
                is None
            )
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=owner_id,
            account_id=shared_account_id,
            bucket=NOW,
            suffix=f"owner-{suffix}",
        )
        async with sessions() as session:
            await BackgroundJobRepository(session).complete(
                lease=claimed.lease,
                result={"published": True},
                progress=_complete_progress(),
                now=NOW,
            )
            await session.commit()

        async with engine.connect() as connection:
            status, finished_at = (
                await connection.execute(
                    select(BackgroundJobModel.status, BackgroundJobModel.finished_at).where(
                        BackgroundJobModel.id == job_id
                    )
                )
            ).one()
            published = tuple(
                (
                    await connection.execute(
                        select(
                            ImportJobPublicationTargetModel.user_id,
                            ImportJobPublicationTargetModel.bucket,
                            ImportJobPublicationTargetModel.published_at,
                        )
                        .where(ImportJobPublicationTargetModel.job_id == job_id)
                        .order_by(ImportJobPublicationTargetModel.user_id)
                    )
                ).all()
            )
        assert status is BackgroundJobStatus.completed
        assert finished_at == NOW
        assert published == ((owner_id, NOW, NOW),)
    finally:
        await _cleanup(
            engine,
            job_ids=(job_id, missing_job_id),
            account_ids=(shared_account_id, missing_account_id),
            user_ids=(owner_id, viewer_id),
        )
        await engine.dispose()


@pytest.mark.integration
async def test_same_user_distinct_jobs_defer_to_immutable_future_bucket_without_attempt_loss() -> (
    None
):
    """A second same-minute job yields, keeps its reservation, then completes later."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id = f"target-user-{suffix}"
    account_a, account_b = f"target-account-a-{suffix}", f"target-account-b-{suffix}"
    job_a, job_b = f"target-job-a-{suffix}", f"target-job-b-{suffix}"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Publication deferral test",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            for account_id in (account_a, account_b):
                await connection.execute(
                    insert(AccountModel).values(
                        id=account_id,
                        name="Publication deferral account",
                        type=AccountType.broker,
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
                    insert(AccountMemberModel).values(
                        id=f"target-member-{account_id}",
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
                insert(BackgroundJobModel).values(**_job(job_a, user_id, account_a))
            )
            await connection.execute(
                insert(BackgroundJobModel).values(**_job(job_b, user_id, account_b))
            )

        claimed_a = await _claim(sessions, job_id=job_a, worker_id="target-first", now=NOW)
        claimed_b = await _claim(sessions, job_id=job_b, worker_id="target-second", now=NOW)
        async with sessions() as session:
            target_a = await ImportJobPublicationService(session).reserve(
                job_id=job_a, account_id=account_a, requested_bucket=NOW
            )
        async with sessions() as session:
            target_b = await ImportJobPublicationService(session).reserve(
                job_id=job_b, account_id=account_b, requested_bucket=NOW
            )
        assert target_a == (target_a[0],)
        assert target_b == (target_b[0],)
        assert target_a[0].bucket == NOW
        assert target_b[0].bucket == NOW + timedelta(minutes=1)

        async with sessions() as session:
            await BackgroundJobRepository(session).defer(
                lease=claimed_b.lease,
                run_after=target_b[0].bucket,
                now=NOW,
            )
            await session.commit()
        async with engine.connect() as connection:
            deferred = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.run_after,
                    ).where(BackgroundJobModel.id == job_b)
                )
            ).one()
        assert deferred == (BackgroundJobStatus.retry_wait, 0, NOW + timedelta(minutes=1))

        resumed = await _claim(
            sessions,
            job_id=job_b,
            worker_id="target-second-resumed",
            now=target_b[0].bucket,
        )
        assert resumed.job.attempt_count == 1
        # A long retry may reach final publication after its first unused
        # reservation. No snapshot/anchor exists yet, so it must retarget to
        # the current minute instead of acquiring stale market evidence.
        async with sessions() as session:
            retargeted = await ImportJobPublicationService(session).reserve(
                job_id=job_b,
                account_id=account_b,
                requested_bucket=NOW + timedelta(minutes=5),
            )
        assert retargeted[0].bucket == NOW + timedelta(minutes=5)
        await _insert_import_anchor(
            engine,
            job_id=job_b,
            user_id=user_id,
            account_id=account_b,
            bucket=retargeted[0].bucket,
            suffix=f"deferred-{suffix}",
        )
        async with sessions() as session:
            await BackgroundJobRepository(session).complete(
                lease=resumed.lease,
                result={"published": True},
                progress=_complete_progress(),
                now=retargeted[0].bucket,
            )
            await session.commit()
        async with engine.connect() as connection:
            completed = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        ImportJobPublicationTargetModel.bucket,
                        ImportJobPublicationTargetModel.published_at,
                    )
                    .join(
                        ImportJobPublicationTargetModel,
                        ImportJobPublicationTargetModel.job_id == BackgroundJobModel.id,
                    )
                    .where(BackgroundJobModel.id == job_b)
                )
            ).one()
        assert completed == (
            BackgroundJobStatus.completed,
            1,
            NOW + timedelta(minutes=5),
            NOW + timedelta(minutes=5),
        )
        del claimed_a
    finally:
        await _cleanup(
            engine,
            job_ids=(job_a, job_b),
            account_ids=(account_a, account_b),
            user_ids=(user_id,),
        )
        await engine.dispose()


@pytest.mark.integration
async def test_canonical_change_after_anchor_defers_then_retires_stale_anchor_for_republish() -> (
    None
):
    """A changed canonical revision cannot publish stale evidence and recovers on retry."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id, job_id = (
        f"stale-user-{suffix}",
        f"stale-account-{suffix}",
        f"stale-job-{suffix}",
    )
    retry_at = NOW + timedelta(minutes=1)
    try:
        await _seed_single_publication(
            engine, user_id=user_id, account_id=account_id, job_id=job_id
        )
        claimed = await _claim(sessions, job_id=job_id, worker_id="stale-first", now=NOW)
        async with sessions() as session:
            targets = await ImportJobPublicationService(session).reserve(
                job_id=job_id, account_id=account_id, requested_bucket=NOW
            )
        assert targets == (targets[0],)
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=user_id,
            account_id=account_id,
            bucket=NOW,
            suffix=f"stale-old-{suffix}",
            canonical_revision=0,
        )

        # A real committed, backdated canonical change arrives after the
        # immutable anchor is written but before atomic publication.
        async with sessions() as session:
            async with session.begin():
                change = await CanonicalStateService(session).record(
                    account_id=account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=f"stale-canonical-{suffix}",
                    financial_timestamp=NOW - timedelta(days=1),
                    created_at=NOW,
                    replay=False,
                )
        assert change.revision == 1
        async with sessions() as session:
            with pytest.raises(BackgroundJobPublicationStaleError):
                await BackgroundJobRepository(session).complete(
                    lease=claimed.lease,
                    result={"published": True},
                    progress=_complete_progress(),
                    now=NOW,
                )
            await session.rollback()

        # The worker maps that stable internal signal to retry_wait rather
        # than abandoning a leased running job. The next finalization retires
        # only the unpublished, job-linked stale evidence.
        async with sessions() as session:
            await BackgroundJobRepository(session).schedule_retry(
                lease=claimed.lease,
                run_after=retry_at,
                error_code="import_publication_stale",
                error_message="Portfolio publication changed and will be retried.",
                now=NOW,
            )
            await session.commit()
        resumed = await _claim(sessions, job_id=job_id, worker_id="stale-resumed", now=retry_at)
        async with sessions() as session:
            fresh_targets = await ImportJobPublicationService(session).reserve(
                job_id=job_id, account_id=account_id, requested_bucket=retry_at
            )
        assert fresh_targets == (fresh_targets[0],)
        assert fresh_targets[0].bucket == retry_at
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(DailySnapshotBaselineModel.id).where(
                        DailySnapshotBaselineModel.background_job_id == job_id
                    )
                )
                is None
            )
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=user_id,
            account_id=account_id,
            bucket=retry_at,
            suffix=f"stale-new-{suffix}",
            canonical_revision=1,
        )
        async with sessions() as session:
            await BackgroundJobRepository(session).complete(
                lease=resumed.lease,
                result={"published": True},
                progress=_complete_progress(),
                now=retry_at,
            )
            await session.commit()
        async with engine.connect() as connection:
            status, target_bucket, published_at = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        ImportJobPublicationTargetModel.bucket,
                        ImportJobPublicationTargetModel.published_at,
                    )
                    .join(
                        ImportJobPublicationTargetModel,
                        ImportJobPublicationTargetModel.job_id == BackgroundJobModel.id,
                    )
                    .where(BackgroundJobModel.id == job_id)
                )
            ).one()
        assert (status, target_bucket, published_at) == (
            BackgroundJobStatus.completed,
            retry_at,
            retry_at,
        )
    finally:
        await _cleanup(
            engine,
            job_ids=(job_id,),
            account_ids=(account_id,),
            user_ids=(user_id,),
        )
        await engine.dispose()


@pytest.mark.integration
async def test_manual_snapshot_after_unused_target_retargets_without_deleting_manual_evidence() -> (
    None
):
    """Manual same-minute evidence cannot permanently fence an unused import target."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id, job_id = (
        f"manual-user-{suffix}",
        f"manual-account-{suffix}",
        f"manual-job-{suffix}",
    )
    advanced = NOW + timedelta(minutes=1)
    manual_snapshot_id = f"manual-net-worth-{suffix}"
    try:
        await _seed_single_publication(
            engine, user_id=user_id, account_id=account_id, job_id=job_id
        )
        claimed = await _claim(sessions, job_id=job_id, worker_id="manual-race", now=NOW)
        async with sessions() as session:
            reserved = await ImportJobPublicationService(session).reserve(
                job_id=job_id, account_id=account_id, requested_bucket=NOW
            )
        assert reserved[0].bucket == NOW
        # An unrelated user-visible manual snapshot arrives after the target.
        async with engine.begin() as connection:
            await connection.execute(
                insert(NetWorthSnapshotModel).values(
                    id=manual_snapshot_id,
                    user_id=user_id,
                    timestamp=NOW,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.manual_recalculation,
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
        async with sessions() as session:
            retargeted = await ImportJobPublicationService(session).reserve(
                job_id=job_id, account_id=account_id, requested_bucket=advanced
            )
        assert retargeted == (retargeted[0],)
        assert retargeted[0].bucket == advanced
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(NetWorthSnapshotModel.id).where(
                        NetWorthSnapshotModel.id == manual_snapshot_id
                    )
                )
                == manual_snapshot_id
            )
        await _insert_import_anchor(
            engine,
            job_id=job_id,
            user_id=user_id,
            account_id=account_id,
            bucket=advanced,
            suffix=f"manual-import-{suffix}",
        )
        async with sessions() as session:
            await BackgroundJobRepository(session).complete(
                lease=claimed.lease,
                result={"published": True},
                progress=_complete_progress(),
                now=advanced,
            )
            await session.commit()
        async with engine.connect() as connection:
            status, target_bucket = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        ImportJobPublicationTargetModel.bucket,
                    )
                    .join(
                        ImportJobPublicationTargetModel,
                        ImportJobPublicationTargetModel.job_id == BackgroundJobModel.id,
                    )
                    .where(BackgroundJobModel.id == job_id)
                )
            ).one()
        assert (status, target_bucket) == (BackgroundJobStatus.completed, advanced)
    finally:
        await _cleanup(
            engine,
            job_ids=(job_id,),
            account_ids=(account_id,),
            user_ids=(user_id,),
        )
        await engine.dispose()
