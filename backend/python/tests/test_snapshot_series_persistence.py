import asyncio
import os
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
    UserReadModelPublicationWatermarkModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobStatus,
    SnapshotGranularity,
    SnapshotSeriesJobKind,
    SnapshotSource,
)
from app.db.models.investment_snapshots import PortfolioSnapshotInputModel, PortfolioSnapshotModel
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel,
    SnapshotSeriesRebuildJobModel,
)
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
    SnapshotSeriesPublicationReceiptModel,
    SnapshotSeriesVersionStateModel,
)
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.daily_baselines.service import DailyBaselineError, _publish_read_model_version
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.portfolio_history.lattice import HistoryPublicRange
from app.modules.portfolio_snapshot.history_reader import PublishedPortfolioSnapshotHistoryReader
from app.modules.snapshot_refresh.series_executor import (
    ExecuteSnapshotSeriesCommand,
    SnapshotSeriesAccountEvidence,
    SnapshotSeriesAccountSelection,
    SnapshotSeriesExecutionStateError,
    SnapshotSeriesExecutor,
    SnapshotSeriesPoint,
    SnapshotSeriesPublicationManifest,
    SnapshotSeriesPublicationSupersededError,
    SnapshotSeriesTarget,
    StageUserSnapshotSeriesProjectionCommand,
    generation_id_for_job,
)
from app.modules.snapshot_refresh.series_persistence import (
    PostgresAtomicSnapshotSeriesPublisher,
    PostgresSnapshotSeriesAccountStager,
    PostgresSnapshotSeriesUserProjectionStager,
    SnapshotSeriesPersistenceError,
)
from app.modules.snapshots.account_projection import (
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)

DATABASE_URL = os.getenv("DATABASE_URL")
_INTEGRATION = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
_AT = datetime(2034, 5, 1, 12)


@pytest.mark.asyncio
async def test_user_stager_rejects_mismatched_native_scope_before_database_access() -> None:
    accessed = False

    def session_factory():
        nonlocal accessed
        accessed = True
        raise AssertionError("database must not be opened")

    command = StageUserSnapshotSeriesProjectionCommand(
        generation_id="generation",
        user_id="user",
        timestamp=datetime(2034, 5, 1),
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=datetime(2034, 5, 1, 0, 0, 1),
        created_at=datetime(2034, 5, 1, 0, 0, 2),
        is_recalculated=True,
        output_currency="EUR",
        output_account_snapshots=(SelectedAccountSnapshotIdentity("account-a", "output"),),
        native_account_snapshots=(SnapshotSeriesAccountSelection("account-b", "native", "USD"),),
    )

    with pytest.raises(SnapshotSeriesPersistenceError):
        await PostgresSnapshotSeriesUserProjectionStager(session_factory).stage(command)

    assert accessed is False


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


def _evidence(
    account_id: str, currency: str, timestamp: datetime
) -> CompleteAccountSnapshotEvidence:
    amount = CurrencyAmount(currency=currency, amount=Decimal(0))
    metric = ExactSnapshotMetric(value=Decimal(0), breakdown=(amount,))
    return CompleteAccountSnapshotEvidence(
        valuation=ExpectedAccountSnapshotValuation(
            account_id=account_id,
            timestamp=timestamp,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.holdings_recalculation,
            currency=currency,
            calculation_version=1,
            cash_value=Decimal(0),
            investment_value=Decimal(0),
            investment_cost_basis=Decimal(0),
            liabilities_value=Decimal(0),
            total_value=Decimal(0),
            cash_value_by_currency=(amount,),
            investment_value_by_currency=(),
            investment_cost_basis_by_currency=(),
            liabilities_value_by_currency=(),
            exchange_rates=(),
            items=(),
        ),
        net_deposits=metric,
        realized_pnl=metric,
        unrealized_pnl=metric,
        fees=metric,
        taxes=metric,
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(),
        selected_historical_exchange_rate_ids=(),
    )


def _series_command(
    prefix: str,
    job_id: str,
    *,
    created_at_offset: timedelta = timedelta(seconds=2),
    start_index: int = 0,
    point_count: int = 2,
) -> ExecuteSnapshotSeriesCommand:
    account_id = f"{prefix}-account"
    points: list[SnapshotSeriesPoint] = []
    for index in range(start_index, start_index + point_count):
        timestamp = _AT + timedelta(minutes=index)
        points.append(
            SnapshotSeriesPoint(
                timestamp=timestamp,
                granularity=SnapshotGranularity.minute,
                source=SnapshotSource.holdings_recalculation,
                calculation_version=1,
                calculated_at=timestamp + timedelta(seconds=1),
                created_at=timestamp + created_at_offset,
                is_recalculated=False,
                account_evidence=tuple(
                    SnapshotSeriesAccountEvidence(
                        account_id=account_id,
                        account_currency="USD",
                        evidence=_evidence(account_id, currency, timestamp),
                        canonical_revision=1,
                        investment_revision=1,
                        holding_revision=1,
                    )
                    for currency in ("EUR", "USD")
                ),
            )
        )
    return ExecuteSnapshotSeriesCommand(
        job_id=job_id,
        targets=(
            SnapshotSeriesTarget(
                user_id=f"{prefix}-user", output_currency="EUR", account_ids=(account_id,)
            ),
        ),
        points=tuple(points),
    )


async def _cleanup(prefix: str, job_ids: tuple[str, ...]) -> None:
    engine = _engine()
    user_ids = (f"{prefix}-user", f"{prefix}-extra")
    account_id = f"{prefix}-account"
    generation_ids = tuple(generation_id_for_job(job_id) for job_id in job_ids)
    try:
        async with AsyncSession(engine) as session:
            # Fixture teardown only: publication metadata is intentionally immutable
            # while a user exists. This transaction runs in the disposable test DB.
            await session.execute(text("SET LOCAL session_replication_role = replica"))
            await session.execute(
                delete(UserReadModelPublicationModel).where(
                    UserReadModelPublicationModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(SnapshotSeriesPublicationReceiptModel).where(
                    SnapshotSeriesPublicationReceiptModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(SnapshotSeriesPointLinkModel).where(
                    SnapshotSeriesPointLinkModel.user_id.in_(user_ids)
                )
            )
            heads = tuple(
                (
                    await session.scalars(
                        select(SnapshotSeriesHeadModel)
                        .where(SnapshotSeriesHeadModel.user_id.in_(user_ids))
                        .order_by(SnapshotSeriesHeadModel.version.desc())
                    )
                ).all()
            )
            for head in heads:
                await session.delete(head)
                await session.flush()
            await session.execute(
                delete(SnapshotSeriesVersionStateModel).where(
                    SnapshotSeriesVersionStateModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(SnapshotSeriesDirtyStateModel).where(
                    SnapshotSeriesDirtyStateModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(DailySnapshotBaselineModel).where(
                    DailySnapshotBaselineModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(PortfolioSnapshotModel).where(PortfolioSnapshotModel.user_id.in_(user_ids))
            )
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
            await session.execute(
                delete(SnapshotGenerationTargetModel).where(
                    SnapshotGenerationTargetModel.generation_id.in_(generation_ids)
                )
            )
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
            )
            await session.execute(
                delete(AccountCanonicalStateModel).where(
                    AccountCanonicalStateModel.account_id == account_id
                )
            )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
            )
            await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
            await session.execute(
                delete(SnapshotGenerationModel).where(
                    SnapshotGenerationModel.id.in_(generation_ids)
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _seed(prefix: str) -> None:
    await _cleanup(prefix, (f"{prefix}-main", f"{prefix}-extra"))
    engine = _engine()
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                (
                    UserModel(
                        id=user_id,
                        email=f"{prefix}@example.test",
                        name="Series",
                        password_hash=None,
                        base_currency="EUR",
                        created_at=_AT,
                        updated_at=_AT,
                    ),
                    UserModel(
                        id=f"{prefix}-extra",
                        email=f"{prefix}-extra@example.test",
                        name="Extra",
                        password_hash=None,
                        base_currency="EUR",
                        created_at=_AT,
                        updated_at=_AT,
                    ),
                    AccountModel(
                        id=account_id,
                        name="Series account",
                        type=AccountType.broker,
                        currency="USD",
                        color=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=_AT,
                        updated_at=_AT,
                        notes=None,
                    ),
                )
            )
            await session.flush()
            canonical_state = await session.get(AccountCanonicalStateModel, account_id)
            assert canonical_state is not None
            canonical_state.last_revision = 1
            canonical_state.last_investment_revision = 1
            canonical_state.holding_revision = 1
            canonical_state.updated_at = _AT
            session.add_all(
                (
                    AccountMemberModel(
                        id=f"{prefix}-member",
                        account_id=account_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=_AT,
                        created_at=_AT,
                        updated_at=_AT,
                    ),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@_INTEGRATION
@pytest.mark.asyncio
async def test_refresh_retains_history_and_dirty_rebuild_replaces_only_suffix() -> None:
    prefix = f"series-temporal-{uuid4().hex}"
    job_ids = tuple(f"{prefix}-{kind}" for kind in ("initial", "capture", "rebuild", "blocked"))
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    executor = SnapshotSeriesExecutor(
        account_stager=PostgresSnapshotSeriesAccountStager(factory),
        user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
        publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
    )
    user_id = f"{prefix}-user"
    try:
        initial = await executor.execute(
            _series_command(
                prefix,
                job_ids[0],
                point_count=3,
            )
        )
        capture = await executor.execute(
            replace(
                _series_command(prefix, job_ids[1], start_index=3, point_count=1),
                causal_at=_AT + timedelta(minutes=4),
            )
        )
        async with factory() as session:
            before = tuple(
                (
                    await session.scalars(
                        select(SnapshotSeriesPointLinkModel)
                        .where(
                            SnapshotSeriesPointLinkModel.user_id == user_id,
                            SnapshotSeriesPointLinkModel.valid_to_version.is_(None),
                        )
                        .order_by(SnapshotSeriesPointLinkModel.timestamp)
                    )
                ).all()
            )
            assert len(before) == 4
            assert [item.baseline_id for item in before[:3]] == [
                item.baseline_id for item in initial.user_projections
            ]
            assert before[-1].baseline_id == capture.user_projections[0].baseline_id
        async with factory() as session, session.begin():
            session.add(
                SnapshotSeriesDirtyStateModel(
                    user_id=user_id,
                    dirty_from=_AT + timedelta(minutes=1),
                    dirty_epoch=1,
                    scope_dirty=False,
                    reason_mask=1,
                    requested_at=_AT + timedelta(minutes=5),
                    updated_at=_AT + timedelta(minutes=5),
                )
            )
        with pytest.raises(SnapshotSeriesExecutionStateError):
            await executor.execute(
                replace(
                    _series_command(prefix, job_ids[3], start_index=4, point_count=1),
                    causal_at=_AT + timedelta(minutes=5),
                )
            )
        async with factory() as session:
            state = await session.get(SnapshotSeriesVersionStateModel, user_id)
            assert state is not None
            assert state.last_version == 2
        rebuilt = await executor.execute(
            replace(
                _series_command(prefix, job_ids[2], start_index=1, point_count=3),
                causal_at=_AT + timedelta(minutes=6),
                replace_from=_AT + timedelta(minutes=1),
                dirty_epoch=1,
            )
        )
        replay = await executor.execute(
            replace(
                _series_command(prefix, job_ids[1], start_index=3, point_count=1),
                causal_at=_AT + timedelta(minutes=4),
            )
        )
        assert replay.generation_id == capture.generation_id
        assert replay.account_snapshots == replay.user_projections == ()
        async with factory() as session:
            current = tuple(
                (
                    await session.scalars(
                        select(SnapshotSeriesPointLinkModel)
                        .where(
                            SnapshotSeriesPointLinkModel.user_id == user_id,
                            SnapshotSeriesPointLinkModel.valid_to_version.is_(None),
                        )
                        .order_by(SnapshotSeriesPointLinkModel.timestamp)
                    )
                ).all()
            )
            assert len(current) == 4
            assert current[0].id == before[0].id
            assert current[0].generation_id == before[0].generation_id
            assert current[0].baseline_id == before[0].baseline_id
            assert current[0].portfolio_snapshot_id == before[0].portfolio_snapshot_id
            assert current[0].net_worth_snapshot_id == before[0].net_worth_snapshot_id
            assert [item.baseline_id for item in current[1:]] == [
                item.baseline_id for item in rebuilt.user_projections
            ]
            closed = tuple(
                (
                    await session.scalars(
                        select(SnapshotSeriesPointLinkModel).where(
                            SnapshotSeriesPointLinkModel.id.in_(item.id for item in before[1:])
                        )
                    )
                ).all()
            )
            assert all(item.valid_to_version == 3 for item in closed)
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            assert pointer is not None
            head = await session.get(SnapshotSeriesHeadModel, pointer.series_head_id)
            assert head is not None
            assert head.version == 3
    finally:
        await engine.dispose()
        await _cleanup(prefix, job_ids)


class _CheckingPublisher:
    def __init__(self, factory: async_sessionmaker[AsyncSession], user_id: str) -> None:
        self._factory = factory
        self._user_id = user_id
        self._delegate = PostgresAtomicSnapshotSeriesPublisher(factory)

    async def publish(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        async with self._factory() as session:
            assert await session.get(UserReadModelPublicationModel, self._user_id) is None
        await self._delegate.publish(manifest)

    async def retire_user(self, _user_id: str, *, job_created_at: datetime) -> None:
        del job_created_at
        raise AssertionError("retirement is not expected")


class _ExtraTargetStager:
    def __init__(self, factory: async_sessionmaker[AsyncSession], prefix: str) -> None:
        self._delegate = PostgresSnapshotSeriesUserProjectionStager(factory)
        self._factory = factory
        self._extra_user_id = f"{prefix}-extra"
        self._injected = False

    async def stage(self, command: StageUserSnapshotSeriesProjectionCommand):
        result = await self._delegate.stage(command)
        if not self._injected:
            self._injected = True
            async with self._factory() as session, session.begin():
                session.add(
                    SnapshotGenerationTargetModel(
                        generation_id=command.generation_id,
                        user_id=self._extra_user_id,
                        created_at=command.created_at,
                    )
                )
        return result


class _RecordingPublisher:
    def __init__(self) -> None:
        self.manifest: SnapshotSeriesPublicationManifest | None = None

    async def publish(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        self.manifest = manifest

    async def retire_user(self, _user_id: str, *, job_created_at: datetime) -> None:
        del job_created_at
        raise AssertionError("retirement is not expected")


class _HeartbeatBlockingPublisher(PostgresAtomicSnapshotSeriesPublisher):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        verification_started: asyncio.Event,
        heartbeat_attempted: asyncio.Event,
        heartbeat_finished: asyncio.Event,
    ) -> None:
        super().__init__(factory)
        self._verification_started = verification_started
        self._heartbeat_attempted = heartbeat_attempted
        self._heartbeat_finished = heartbeat_finished

    async def _verify_exact_manifest(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        self._verification_started.set()
        await self._heartbeat_attempted.wait()
        await asyncio.sleep(0.05)
        assert not self._heartbeat_finished.is_set()
        await super()._verify_exact_manifest(session, manifest)


class _UserBlockingPublisher(PostgresAtomicSnapshotSeriesPublisher):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        verification_started: asyncio.Event,
        update_attempted: asyncio.Event,
        update_finished: asyncio.Event,
    ) -> None:
        super().__init__(factory)
        self._verification_started = verification_started
        self._update_attempted = update_attempted
        self._update_finished = update_finished

    async def _verify_exact_manifest(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        self._verification_started.set()
        await self._update_attempted.wait()
        await asyncio.sleep(0.05)
        assert not self._update_finished.is_set()
        await super()._verify_exact_manifest(session, manifest)


class _SerializationRetryPublisher(PostgresAtomicSnapshotSeriesPublisher):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(factory)
        self.manifests: list[SnapshotSeriesPublicationManifest] = []

    async def _publish_once(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        self.manifests.append(manifest)
        if len(self.manifests) == 1:
            original = RuntimeError("serialization conflict")
            original.sqlstate = "40001"  # type: ignore[attr-defined]
            raise DBAPIError(None, None, original, False)
        await super()._publish_once(manifest)


@_INTEGRATION
@pytest.mark.asyncio
async def test_publication_locks_worker_lease_before_manifest_verification() -> None:
    prefix = f"series-heartbeat-fence-{uuid4().hex}"
    job_id = f"{prefix}-main"
    user_id = f"{prefix}-user"
    worker_id = f"{prefix}-worker"
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    verification_started = asyncio.Event()
    heartbeat_attempted = asyncio.Event()
    heartbeat_finished = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    try:
        async with factory() as session, session.begin():
            session.add(
                SnapshotSeriesRebuildJobModel(
                    id=job_id,
                    user_id=user_id,
                    requested_by_background_job_id=None,
                    kind=SnapshotSeriesJobKind.rebuild,
                    status=BackgroundJobStatus.running,
                    idempotency_key=f"{prefix}-key",
                    payload={"schema_version": 1},
                    checkpoint={},
                    progress={},
                    result=None,
                    error_code=None,
                    error_message=None,
                    attempt_count=1,
                    manual_retry_count=0,
                    max_attempts=3,
                    run_after=_AT,
                    lease_owner=worker_id,
                    lease_version=1,
                    lease_expires_at=_AT + timedelta(days=1),
                    lease_heartbeat_at=_AT,
                    started_at=_AT,
                    finished_at=None,
                    created_at=_AT,
                    updated_at=_AT,
                )
            )
        command = replace(
            _series_command(prefix, job_id),
            causal_at=_AT,
            staged_by_job_id=job_id,
            staged_lease_version=1,
            staged_lease_owner=worker_id,
        )
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(command)
        assert recorder.manifest is not None

        async def heartbeat() -> None:
            await verification_started.wait()
            async with factory() as session, session.begin():
                heartbeat_attempted.set()
                await session.execute(
                    update(SnapshotSeriesRebuildJobModel)
                    .where(SnapshotSeriesRebuildJobModel.id == job_id)
                    .values(
                        lease_heartbeat_at=_AT + timedelta(seconds=1),
                        updated_at=_AT + timedelta(seconds=1),
                    )
                )
            heartbeat_finished.set()

        heartbeat_task = asyncio.create_task(heartbeat())
        await _HeartbeatBlockingPublisher(
            factory,
            verification_started,
            heartbeat_attempted,
            heartbeat_finished,
        ).publish(recorder.manifest)
        await heartbeat_task
        assert heartbeat_finished.is_set()
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            assert pointer is not None
            assert pointer.generation_id == recorder.manifest.generation_id
    finally:
        if heartbeat_task is not None and not heartbeat_task.done():
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        await engine.dispose()
        await _cleanup(prefix, (job_id,))


@_INTEGRATION
@pytest.mark.asyncio
async def test_publication_locks_user_before_manifest_verification() -> None:
    prefix = f"series-user-fence-{uuid4().hex}"
    job_id = f"{prefix}-main"
    user_id = f"{prefix}-user"
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    verification_started = asyncio.Event()
    update_attempted = asyncio.Event()
    update_finished = asyncio.Event()
    update_task: asyncio.Task[None] | None = None
    try:
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(_series_command(prefix, job_id))
        assert recorder.manifest is not None

        async def update_user() -> None:
            await verification_started.wait()
            async with factory() as session, session.begin():
                update_attempted.set()
                await session.execute(
                    update(UserModel)
                    .where(UserModel.id == user_id)
                    .values(updated_at=_AT + timedelta(seconds=1))
                )
            update_finished.set()

        update_task = asyncio.create_task(update_user())
        await _UserBlockingPublisher(
            factory,
            verification_started,
            update_attempted,
            update_finished,
        ).publish(recorder.manifest)
        await update_task
        assert update_finished.is_set()
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            assert pointer is not None
            assert pointer.generation_id == recorder.manifest.generation_id
    finally:
        if update_task is not None and not update_task.done():
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)
        await engine.dispose()
        await _cleanup(prefix, (job_id,))


@_INTEGRATION
@pytest.mark.asyncio
async def test_publication_retries_serialization_without_rebuilding_manifest() -> None:
    prefix = f"series-serialization-retry-{uuid4().hex}"
    job_id = f"{prefix}-main"
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    try:
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(_series_command(prefix, job_id))
        assert recorder.manifest is not None

        publisher = _SerializationRetryPublisher(factory)
        await publisher.publish(recorder.manifest)

        assert len(publisher.manifests) == 2
        assert all(item is recorder.manifest for item in publisher.manifests)
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, f"{prefix}-user")
            assert pointer is not None
            assert pointer.generation_id == recorder.manifest.generation_id
    finally:
        await engine.dispose()
        await _cleanup(prefix, (job_id,))


@_INTEGRATION
@pytest.mark.asyncio
async def test_postgres_series_stages_exact_companions_publishes_once_and_rejects_extras() -> None:
    prefix = f"series-persistence-{uuid4().hex}"
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    main_command = _series_command(prefix, f"{prefix}-main")
    try:
        first = await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=_CheckingPublisher(factory, f"{prefix}-user"),
        ).execute(main_command)
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, f"{prefix}-user")
            assert pointer is not None
            assert pointer.generation_id == first.generation_id
            assert pointer.baseline_id == first.user_projections[-1].baseline_id
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.generation_id == first.generation_id)
                )
            ) == 4
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.generation_id == first.generation_id)
                )
            ) == 2
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PortfolioSnapshotModel)
                    .where(PortfolioSnapshotModel.generation_id == first.generation_id)
                )
            ) == 2
            assert {item.currency for item in first.account_snapshots} == {"EUR", "USD"}
            assert (
                first.user_projections[0].output_account_snapshots[0].snapshot_id
                != first.user_projections[0].native_account_snapshots[0].snapshot_id
            )
        principal = AuthenticatedPrincipal(
            user_id=f"{prefix}-user",
            email=f"{prefix}@example.test",
            name="Series",
        )
        async with factory() as session:
            reader = PublishedPortfolioSnapshotHistoryReader(session)
            account_history = await reader.read(
                principal=principal,
                history_range=HistoryPublicRange.all,
                account_id=f"{prefix}-account",
            )
            assert account_history.currency == "USD"
            assert account_history.valuation_timestamp == _AT + timedelta(minutes=1, seconds=1)
        replay = await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
        ).execute(main_command)
        assert replay.generation_id == first.generation_id
        assert replay.account_snapshots == replay.user_projections == ()
        with pytest.raises(SnapshotSeriesExecutionStateError):
            await SnapshotSeriesExecutor(
                account_stager=PostgresSnapshotSeriesAccountStager(factory),
                user_projection_stager=_ExtraTargetStager(factory, prefix),
                publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
            ).execute(_series_command(prefix, f"{prefix}-extra"))
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, f"{prefix}-user")
            assert pointer is not None and pointer.generation_id == first.generation_id
            foreign_keys = set(
                (
                    await session.scalars(
                        text(
                            "SELECT constraint_name FROM information_schema.table_constraints "
                            "WHERE table_schema = 'public' "
                            "AND table_name = 'PortfolioSnapshotInput' "
                            "AND constraint_type = 'FOREIGN KEY'"
                        )
                    )
                ).all()
            )
            assert "PortfolioSnapshotInput_authorized_account_user_fkey" not in foreign_keys
            input_count = await session.scalar(
                select(func.count())
                .select_from(PortfolioSnapshotInputModel)
                .where(PortfolioSnapshotInputModel.user_id == f"{prefix}-user")
            )
            assert input_count is not None and input_count > 0
            await session.execute(
                delete(AccountMemberModel).where(
                    AccountMemberModel.account_id == f"{prefix}-account",
                    AccountMemberModel.user_id == f"{prefix}-user",
                )
            )
            await session.commit()
        async with factory() as session:
            aggregate_history = await PublishedPortfolioSnapshotHistoryReader(session).read(
                principal=principal,
                history_range=HistoryPublicRange.all,
                account_id=None,
            )
            assert aggregate_history.points == ()
    finally:
        await engine.dispose()
        await _cleanup(prefix, (f"{prefix}-main", f"{prefix}-extra"))


@_INTEGRATION
@pytest.mark.asyncio
async def test_postgres_series_rejects_an_older_staged_generation_after_newer_publication() -> None:
    prefix = f"series-order-{uuid4().hex}"
    job_ids = (f"{prefix}-old", f"{prefix}-new")
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    try:
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(
            _series_command(
                prefix,
                job_ids[0],
                created_at_offset=timedelta(seconds=2),
            )
        )
        assert recorder.manifest is not None
        newer = await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
        ).execute(
            _series_command(
                prefix,
                job_ids[1],
                created_at_offset=timedelta(seconds=3),
            )
        )

        with pytest.raises(SnapshotSeriesPublicationSupersededError):
            await PostgresAtomicSnapshotSeriesPublisher(factory).publish(recorder.manifest)

        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, f"{prefix}-user")
            assert pointer is not None
            assert pointer.generation_id == newer.generation_id
        publisher = PostgresAtomicSnapshotSeriesPublisher(factory)
        await publisher.retire_user(f"{prefix}-user", job_created_at=_AT)
        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, f"{prefix}-user")
            assert pointer is not None
            assert pointer.generation_id == newer.generation_id
        await publisher.retire_user(
            f"{prefix}-user",
            job_created_at=_AT + timedelta(days=1),
        )
        async with factory() as session:
            assert await session.get(UserReadModelPublicationModel, f"{prefix}-user") is None
        with pytest.raises(SnapshotSeriesPublicationSupersededError):
            await publisher.publish(recorder.manifest)
        async with factory() as session:
            assert await session.get(UserReadModelPublicationModel, f"{prefix}-user") is None
    finally:
        await engine.dispose()
        await _cleanup(prefix, job_ids)


@_INTEGRATION
@pytest.mark.asyncio
async def test_equivalent_older_generation_finalizes_without_repointing_newer_publication() -> None:
    prefix = f"series-equivalent-order-{uuid4().hex}"
    job_ids = (f"{prefix}-old", f"{prefix}-new")
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    user_id = f"{prefix}-user"
    try:
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(_series_command(prefix, job_ids[0], created_at_offset=timedelta(seconds=2)))
        assert recorder.manifest is not None
        older_manifest = recorder.manifest
        older_baseline_id = older_manifest.user_projections[-1].baseline_id

        newer = await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
        ).execute(_series_command(prefix, job_ids[1], created_at_offset=timedelta(seconds=3)))

        async with factory() as session:
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            watermark = await session.get(UserReadModelPublicationWatermarkModel, user_id)
            assert pointer is not None and watermark is not None
            pointer_before = (
                pointer.version,
                pointer.baseline_id,
                pointer.generation_id,
                pointer.generation_state,
                tuple(pointer.scopes),
                pointer.published_at,
            )
            watermark_before = (
                watermark.causal_at,
                watermark.kind,
                watermark.generation_id,
                watermark.updated_at,
            )

        async with factory() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await _publish_read_model_version(
                session,
                user_id=user_id,
                baseline_id=older_baseline_id,
                published_at=_AT + timedelta(minutes=2),
                causal_at=older_manifest.causal_at,
                allow_equivalent_supersession=True,
            )
            await session.commit()

        async with factory() as session:
            older_generation = await session.get(
                SnapshotGenerationModel, older_manifest.generation_id
            )
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            watermark = await session.get(UserReadModelPublicationWatermarkModel, user_id)
            assert older_generation is not None
            assert older_generation.state == "published"
            assert older_generation.published_at == _AT + timedelta(minutes=2)
            assert pointer is not None and watermark is not None
            assert pointer.generation_id == newer.generation_id
            assert (
                pointer.version,
                pointer.baseline_id,
                pointer.generation_id,
                pointer.generation_state,
                tuple(pointer.scopes),
                pointer.published_at,
            ) == pointer_before
            assert (
                watermark.causal_at,
                watermark.kind,
                watermark.generation_id,
                watermark.updated_at,
            ) == watermark_before
    finally:
        await engine.dispose()
        await _cleanup(prefix, job_ids)


@_INTEGRATION
@pytest.mark.asyncio
async def test_equivalent_older_generation_rolls_back_behind_retired_watermark() -> None:
    prefix = f"series-retired-order-{uuid4().hex}"
    job_ids = (f"{prefix}-old", f"{prefix}-new")
    await _seed(prefix)
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recorder = _RecordingPublisher()
    user_id = f"{prefix}-user"
    try:
        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=recorder,
        ).execute(_series_command(prefix, job_ids[0], created_at_offset=timedelta(seconds=2)))
        assert recorder.manifest is not None
        older_manifest = recorder.manifest

        await SnapshotSeriesExecutor(
            account_stager=PostgresSnapshotSeriesAccountStager(factory),
            user_projection_stager=PostgresSnapshotSeriesUserProjectionStager(factory),
            publisher=PostgresAtomicSnapshotSeriesPublisher(factory),
        ).execute(_series_command(prefix, job_ids[1], created_at_offset=timedelta(seconds=3)))
        await PostgresAtomicSnapshotSeriesPublisher(factory).retire_user(
            user_id,
            job_created_at=_AT + timedelta(days=1),
        )
        async with factory() as session:
            watermark = await session.get(UserReadModelPublicationWatermarkModel, user_id)
            assert watermark is not None
            watermark_before = (
                watermark.causal_at,
                watermark.kind,
                watermark.generation_id,
                watermark.updated_at,
            )

        async with factory() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DailyBaselineError):
                await _publish_read_model_version(
                    session,
                    user_id=user_id,
                    baseline_id=older_manifest.user_projections[-1].baseline_id,
                    published_at=_AT + timedelta(minutes=2),
                    causal_at=older_manifest.causal_at,
                    allow_equivalent_supersession=True,
                )
            await session.rollback()

        async with factory() as session:
            older_generation = await session.get(
                SnapshotGenerationModel, older_manifest.generation_id
            )
            pointer = await session.get(UserReadModelPublicationModel, user_id)
            watermark = await session.get(UserReadModelPublicationWatermarkModel, user_id)
            assert older_generation is not None and older_generation.state == "staged"
            assert older_generation.published_at is None
            assert pointer is None
            assert watermark is not None
            assert (
                watermark.causal_at,
                watermark.kind,
                watermark.generation_id,
                watermark.updated_at,
            ) == watermark_before
    finally:
        await engine.dispose()
        await _cleanup(prefix, job_ids)
