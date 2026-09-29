"""PostgreSQL stage and publication adapters for frozen snapshot series.

The executor supplies immutable projections and canonical-boundary values.  These
adapters never rebuild valuation evidence or call a provider: they only persist
that frozen input and make the already-staged generation visible in one
SERIALIZABLE transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
    UserReadModelPublicationWatermarkModel,
)
from app.db.models.enums import BackgroundJobStatus
from app.db.models.investment_snapshots import PortfolioSnapshotModel
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
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.modules.daily_baselines import (
    DailyBaselineError,
    DailySnapshotBaselineService,
    PersistDailySnapshotBaselineCommand,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    WriteNetWorthSnapshotCommand,
)
from app.modules.portfolio_snapshot.writer import (
    PortfolioSnapshotWriteError,
    PortfolioSnapshotWriter,
    WritePortfolioSnapshotCommand,
)
from app.modules.snapshot_refresh.series_executor import (
    SnapshotSeriesAccountManifestEntry,
    SnapshotSeriesPublicationManifest,
    SnapshotSeriesPublicationSupersededError,
    StagedAccountSnapshot,
    StagedUserSnapshotSeriesProjection,
    StageUserSnapshotSeriesProjectionCommand,
)

_ERROR = "Frozen snapshot-series persistence could not be completed."
_SCOPES = ["portfolio", "dashboard"]
_HEAD_NAMESPACE = UUID("e26ac68b-6f55-4841-a4df-ed78279465b6")
_LINK_NAMESPACE = UUID("a91c43b1-3a88-41f5-bd2a-f30429e84ec2")
_RECEIPT_NAMESPACE = UUID("65e5f571-6f74-448a-a9ee-33797f0b7816")
_PUBLICATION_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_PUBLICATION_SQLSTATES = {"40001", "40P01"}


class SnapshotSeriesPersistenceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_ERROR)


type SessionFactory = Callable[[], AsyncSession]
type PortfolioWriterFactory = Callable[[AsyncSession], PortfolioSnapshotWriter]
type NetWorthWriterFactory = Callable[[AsyncSession], NetWorthSnapshotWriter]
type BaselineWriterFactory = Callable[[AsyncSession], DailySnapshotBaselineService]


def _fail() -> SnapshotSeriesPersistenceError:
    return SnapshotSeriesPersistenceError()


def _same_model_values(model: object, values: dict[str, object]) -> bool:
    return all(getattr(model, name) == value for name, value in values.items())


async def _generation_for_stage(
    session: AsyncSession,
    *,
    generation_id: str,
    created_at: datetime,
) -> SnapshotGenerationModel:
    generation = await session.get(SnapshotGenerationModel, generation_id, with_for_update=True)
    if generation is None:
        generation = SnapshotGenerationModel(
            id=generation_id,
            state="staged",
            created_at=created_at,
            published_at=None,
        )
        session.add(generation)
        await session.flush()
    elif (
        generation.state not in {"staged", "published"}
        or (generation.state == "staged" and generation.published_at is not None)
        or (generation.state == "published" and generation.published_at is None)
    ):
        raise _fail()
    return generation


class PostgresSnapshotSeriesAccountStager:
    """Stage one exact account row, items, and frozen canonical boundary."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def stage(self, entry: SnapshotSeriesAccountManifestEntry) -> StagedAccountSnapshot:
        projection = entry.projection
        snapshot = projection.snapshot
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                generation = await _generation_for_stage(
                    session,
                    generation_id=snapshot.generation_id,
                    created_at=snapshot.created_at,
                )
                persisted = await session.get(
                    AccountSnapshotModel, snapshot.id, with_for_update=True
                )
                expected_snapshot = snapshot.model_values()
                expected_items = tuple(item.model_values() for item in projection.items)
                expected_boundary = {
                    "snapshot_id": snapshot.id,
                    "account_id": snapshot.account_id,
                    "canonical_revision": entry.canonical_revision,
                    "investment_revision": entry.investment_revision,
                    "holding_revision": entry.holding_revision,
                    "selected_liability_balance_id": entry.selected_liability_balance_id,
                    "created_at": snapshot.created_at,
                }
                if persisted is None:
                    if generation.state != "staged":
                        raise _fail()
                    session.add(AccountSnapshotModel(**expected_snapshot))
                    # These models intentionally do not expose ORM relationships;
                    # establish the parent FK before inserting its evidence rows.
                    await session.flush()
                    session.add_all(AccountSnapshotItemModel(**item) for item in expected_items)
                    session.add(AccountSnapshotCanonicalBoundaryModel(**expected_boundary))
                    await session.flush()
                    persisted = await session.get(AccountSnapshotModel, snapshot.id)
                if persisted is None or not _same_model_values(persisted, expected_snapshot):
                    raise _fail()
                items = tuple(
                    (
                        await session.scalars(
                            select(AccountSnapshotItemModel)
                            .where(AccountSnapshotItemModel.snapshot_id == snapshot.id)
                            .order_by(
                                AccountSnapshotItemModel.listing_id, AccountSnapshotItemModel.id
                            )
                        )
                    ).all()
                )
                if len(items) != len(expected_items) or any(
                    not _same_model_values(item, expected)
                    for item, expected in zip(items, expected_items, strict=True)
                ):
                    raise _fail()
                boundary = await session.get(AccountSnapshotCanonicalBoundaryModel, snapshot.id)
                if boundary is None or not _same_model_values(boundary, expected_boundary):
                    raise _fail()
        except (SnapshotSeriesPersistenceError, SQLAlchemyError):
            raise
        return StagedAccountSnapshot(
            snapshot_id=snapshot.id,
            account_id=snapshot.account_id,
            timestamp=snapshot.timestamp,
            granularity=snapshot.granularity,
            currency=snapshot.currency,
            generation_id=snapshot.generation_id,
        )


class PostgresSnapshotSeriesUserProjectionStager:
    """Use existing projection writers while keeping their baseline unpublished."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        portfolio_writer_factory: PortfolioWriterFactory = PortfolioSnapshotWriter,
        net_worth_writer_factory: NetWorthWriterFactory = NetWorthSnapshotWriter,
        baseline_writer_factory: BaselineWriterFactory = DailySnapshotBaselineService,
    ) -> None:
        self._session_factory = session_factory
        self._portfolio_writer_factory = portfolio_writer_factory
        self._net_worth_writer_factory = net_worth_writer_factory
        self._baseline_writer_factory = baseline_writer_factory

    async def _ensure_target(self, command: StageUserSnapshotSeriesProjectionCommand) -> None:
        account_ids = tuple(item.account_id for item in command.output_account_snapshots)
        if (
            account_ids != tuple(item.account_id for item in command.native_account_snapshots)
            or account_ids != tuple(sorted(account_ids))
            or len(set(account_ids)) != len(account_ids)
        ):
            raise _fail()
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                generation = await _generation_for_stage(
                    session,
                    generation_id=command.generation_id,
                    created_at=command.created_at,
                )
                memberships = tuple(
                    (
                        await session.scalars(
                            select(AccountMemberModel)
                            .where(
                                AccountMemberModel.user_id == command.user_id,
                                AccountMemberModel.account_id.in_(account_ids),
                            )
                            .with_for_update(read=True)
                        )
                    ).all()
                )
                if {member.account_id for member in memberships} != set(account_ids):
                    raise _fail()
                target = await session.get(
                    SnapshotGenerationTargetModel,
                    (command.generation_id, command.user_id),
                    with_for_update=True,
                )
                if target is None:
                    if generation.state != "staged":
                        raise _fail()
                    session.add(
                        SnapshotGenerationTargetModel(
                            generation_id=command.generation_id,
                            user_id=command.user_id,
                            created_at=generation.created_at,
                            staged_by_job_id=command.staged_by_job_id,
                            staged_lease_version=command.staged_lease_version,
                            staged_lease_owner=command.staged_lease_owner,
                        )
                    )
                elif target.created_at != generation.created_at:
                    raise _fail()
                elif command.staged_by_job_id is not None:
                    if target.staged_by_job_id not in (None, command.staged_by_job_id):
                        raise _fail()
                    target.staged_by_job_id = command.staged_by_job_id
                    target.staged_lease_version = command.staged_lease_version
                    target.staged_lease_owner = command.staged_lease_owner
        except (SnapshotSeriesPersistenceError, SQLAlchemyError):
            raise

    async def stage(
        self, command: StageUserSnapshotSeriesProjectionCommand
    ) -> StagedUserSnapshotSeriesProjection:
        await self._ensure_target(command)
        try:
            async with self._session_factory() as session:
                portfolio = await self._portfolio_writer_factory(session).write(
                    WritePortfolioSnapshotCommand(
                        user_id=command.user_id,
                        generation_id=command.generation_id,
                        timestamp=command.timestamp,
                        granularity=command.granularity,
                        source=command.source,
                        currency=command.output_currency,
                        calculation_version=command.calculation_version,
                        calculated_at=command.calculated_at,
                        created_at=command.created_at,
                        required_account_snapshot_identities=command.output_account_snapshots,
                    )
                )
            async with self._session_factory() as session:
                net_worth: NetWorthSnapshotWriteResult = await self._net_worth_writer_factory(
                    session
                ).write(
                    WriteNetWorthSnapshotCommand(
                        user_id=command.user_id,
                        snapshot_timestamp=command.timestamp,
                        granularity=command.granularity,
                        currency=command.output_currency,
                        source=command.source,
                        calculation_version=command.calculation_version,
                        calculated_at=command.calculated_at,
                        created_at=command.created_at,
                        is_recalculated=command.is_recalculated,
                        required_account_snapshot_identities=command.output_account_snapshots,
                        generation_id=command.generation_id,
                    )
                )
            async with self._session_factory() as session:
                baseline = await self._baseline_writer_factory(session).persist(
                    PersistDailySnapshotBaselineCommand(
                        user_id=command.user_id,
                        net_worth_snapshot_id=net_worth.snapshot_id,
                        timestamp=command.timestamp,
                        granularity=command.granularity,
                        currency=command.output_currency,
                        calculation_version=command.calculation_version,
                        source=command.source,
                        created_at=command.created_at,
                        primary_snapshot_identities=command.output_account_snapshots,
                        publish_read_model=False,
                    )
                )
        except (DailyBaselineError, PortfolioSnapshotWriteError, SQLAlchemyError) as exc:
            raise _fail() from exc
        if (
            portfolio.user_id != command.user_id
            or portfolio.generation_id != command.generation_id
            or net_worth.user_id != command.user_id
            or net_worth.snapshot_id != baseline.net_worth_snapshot_id
        ):
            raise _fail()
        return StagedUserSnapshotSeriesProjection(
            generation_id=command.generation_id,
            user_id=command.user_id,
            timestamp=command.timestamp,
            granularity=command.granularity,
            source=command.source,
            calculation_version=command.calculation_version,
            calculated_at=command.calculated_at,
            created_at=command.created_at,
            is_recalculated=command.is_recalculated,
            output_currency=command.output_currency,
            output_account_snapshots=command.output_account_snapshots,
            native_account_snapshots=command.native_account_snapshots,
            portfolio_snapshot_id=portfolio.portfolio_snapshot_id,
            net_worth_snapshot_id=net_worth.snapshot_id,
            baseline_id=baseline.baseline_id,
        )


async def publish_snapshot_baselines(
    session: AsyncSession,
    *,
    user_id: str,
    baseline_ids: tuple[str, ...],
    operation_id: str,
    published_at: datetime,
    causal_at: datetime,
    replace_from: datetime | None = None,
    dirty_epoch: int | None = None,
    staged_lease: tuple[int | None, str | None] | None = None,
    locked_user: UserModel | None = None,
    locked_staged_job: SnapshotSeriesRebuildJobModel | None = None,
    allow_equivalent_supersession: bool = False,
    allow_dirty_import: bool = False,
) -> None:
    """Publish exact immutable points in the caller's SERIALIZABLE transaction.

    The receipt is checked first: a crash after the pointer switch can resume
    administrative work even if a newer head has since superseded this one.
    """
    if not baseline_ids or len(set(baseline_ids)) != len(baseline_ids):
        raise _fail()
    if (replace_from is None) != (dirty_epoch is None):
        raise _fail()
    user = locked_user
    if user is None:
        user = await session.get(UserModel, user_id, with_for_update=True)
    if user is None or user.id != user_id:
        raise _fail()
    baselines = tuple(
        (
            await session.scalars(
                select(DailySnapshotBaselineModel)
                .where(
                    DailySnapshotBaselineModel.id.in_(baseline_ids),
                    DailySnapshotBaselineModel.user_id == user_id,
                )
                .order_by(DailySnapshotBaselineModel.timestamp)
                .with_for_update()
            )
        ).all()
    )
    if {item.id for item in baselines} != set(baseline_ids):
        raise _fail()
    generation_ids = {item.generation_id for item in baselines}
    if len(generation_ids) != 1:
        raise _fail()
    generation_id = next(iter(generation_ids))
    receipt = await session.scalar(
        select(SnapshotSeriesPublicationReceiptModel).where(
            SnapshotSeriesPublicationReceiptModel.user_id == user_id,
            SnapshotSeriesPublicationReceiptModel.job_id == operation_id,
        )
    )
    if receipt is not None:
        if receipt.generation_id != generation_id:
            raise _fail()
        return
    generation = await session.get(SnapshotGenerationModel, generation_id, with_for_update=True)
    target = await session.get(
        SnapshotGenerationTargetModel, (generation_id, user_id), with_for_update=True
    )
    if generation is None or target is None or generation.state not in {"staged", "published"}:
        raise _fail()
    if staged_lease is not None:
        version, owner = staged_lease
        job = locked_staged_job
        if job is None:
            job = await session.get(
                SnapshotSeriesRebuildJobModel, operation_id, with_for_update=True
            )
        if (
            job is None
            or job.id != operation_id
            or job.user_id != user_id
            or job.status is not BackgroundJobStatus.running
            or job.lease_version != version
            or job.lease_owner != owner
            or job.lease_expires_at is None
            or job.lease_expires_at <= published_at
            or target.staged_by_job_id != operation_id
            or target.staged_lease_version != version
            or target.staged_lease_owner != owner
        ):
            raise _fail()
    pointer = await session.get(UserReadModelPublicationModel, user_id, with_for_update=True)
    watermark = await session.get(
        UserReadModelPublicationWatermarkModel, user_id, with_for_update=True
    )
    dirty = await session.get(SnapshotSeriesDirtyStateModel, user_id, with_for_update=True)
    if replace_from is None:
        if dirty is not None and not allow_dirty_import:
            raise _fail()
    elif dirty is None or dirty.dirty_epoch != dirty_epoch or dirty.dirty_from != replace_from:
        raise _fail()
    conflict = watermark is not None and (
        watermark.causal_at > causal_at
        or (
            watermark.causal_at == causal_at
            and (watermark.kind != "published" or watermark.generation_id != generation_id)
        )
    )
    if conflict:
        assert watermark is not None
        if not allow_equivalent_supersession or len(baselines) != 1:
            raise SnapshotSeriesPublicationSupersededError()
        from app.modules.daily_baselines.service import _is_equivalent_superseding_publication

        if not await _is_equivalent_superseding_publication(
            session,
            user_id=user_id,
            candidate=baselines[0],
            publication=pointer,
            watermark=watermark,
        ):
            raise SnapshotSeriesPublicationSupersededError()
        if generation.state == "staged":
            generation.state = "published"
            generation.published_at = published_at
        return
    coordinates = [(item.timestamp, item.granularity) for item in baselines]
    if len(set(coordinates)) != len(coordinates):
        raise _fail()
    if replace_from is not None and any(item.timestamp < replace_from for item in baselines):
        raise _fail()
    points: list[tuple[DailySnapshotBaselineModel, PortfolioSnapshotModel]] = []
    for baseline in baselines:
        portfolio = await session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.user_id == user_id,
                PortfolioSnapshotModel.generation_id == generation_id,
                PortfolioSnapshotModel.timestamp == baseline.timestamp,
                PortfolioSnapshotModel.granularity == baseline.granularity,
                PortfolioSnapshotModel.currency == baseline.currency,
            )
        )
        # An empty authorized scope is a valid zero-account publication.  The
        # staged manifest verifier has already required the baseline children
        # to match the exact account projections, including the empty tuple.
        if portfolio is None:
            raise _fail()
        points.append((baseline, portfolio))
    state = await session.get(SnapshotSeriesVersionStateModel, user_id, with_for_update=True)
    if state is None:
        state = SnapshotSeriesVersionStateModel(
            user_id=user_id,
            last_version=0,
            updated_at=published_at,
        )
        session.add(state)
        await session.flush()
    version = state.last_version + 1
    head_id = f"series-head:{uuid5(_HEAD_NAMESPACE, f'{user_id}:{version}')}"
    head = SnapshotSeriesHeadModel(
        id=head_id,
        user_id=user_id,
        version=version,
        parent_head_id=pointer.series_head_id if pointer is not None else None,
        generation_id=generation_id,
        created_at=published_at,
    )
    session.add(head)
    await session.flush()
    if replace_from is None:
        for timestamp, granularity in coordinates:
            await session.execute(
                update(SnapshotSeriesPointLinkModel)
                .where(
                    SnapshotSeriesPointLinkModel.user_id == user_id,
                    SnapshotSeriesPointLinkModel.timestamp == timestamp,
                    SnapshotSeriesPointLinkModel.granularity == granularity,
                    SnapshotSeriesPointLinkModel.valid_to_version.is_(None),
                )
                .values(valid_to_version=version)
            )
    else:
        await session.execute(
            update(SnapshotSeriesPointLinkModel)
            .where(
                SnapshotSeriesPointLinkModel.user_id == user_id,
                SnapshotSeriesPointLinkModel.timestamp >= replace_from,
                SnapshotSeriesPointLinkModel.valid_to_version.is_(None),
            )
            .values(valid_to_version=version)
        )
    for baseline, portfolio in points:
        session.add(
            SnapshotSeriesPointLinkModel(
                id=f"series-link:{uuid5(_LINK_NAMESPACE, f'{user_id}:{version}:{baseline.id}')}",
                user_id=user_id,
                timestamp=baseline.timestamp,
                granularity=baseline.granularity,
                valid_from_version=version,
                valid_to_version=None,
                generation_id=generation_id,
                baseline_id=baseline.id,
                portfolio_snapshot_id=portfolio.id,
                net_worth_snapshot_id=baseline.net_worth_snapshot_id,
                created_at=published_at,
            )
        )
    if generation.state == "staged":
        generation.state = "published"
        generation.published_at = published_at
    latest = max(baselines, key=lambda item: item.timestamp)
    if pointer is None:
        session.add(
            UserReadModelPublicationModel(
                user_id=user_id,
                version=head_id,
                baseline_id=latest.id,
                scopes=list(_SCOPES),
                published_at=published_at,
                generation_id=generation_id,
                generation_state="published",
                series_head_id=head_id,
            )
        )
    else:
        pointer.version = head_id
        pointer.baseline_id = latest.id
        pointer.scopes = list(_SCOPES)
        pointer.published_at = published_at
        pointer.generation_id = generation_id
        pointer.generation_state = "published"
        pointer.series_head_id = head_id
    if watermark is None:
        session.add(
            UserReadModelPublicationWatermarkModel(
                user_id=user_id,
                causal_at=causal_at,
                kind="published",
                generation_id=generation_id,
                updated_at=published_at,
            )
        )
    else:
        watermark.causal_at = causal_at
        watermark.kind = "published"
        watermark.generation_id = generation_id
        watermark.updated_at = published_at
    state.last_version = version
    state.updated_at = published_at
    session.add(
        SnapshotSeriesPublicationReceiptModel(
            id=f"series-receipt:{uuid5(_RECEIPT_NAMESPACE, f'{user_id}:{operation_id}')}",
            user_id=user_id,
            job_id=operation_id,
            generation_id=generation_id,
            head_id=head_id,
            committed_at=published_at,
        )
    )
    await session.flush()


class PostgresAtomicSnapshotSeriesPublisher:
    """Verify every expected row, then atomically publish every user pointer."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def has_receipt(
        self, *, operation_id: str, generation_id: str, user_ids: tuple[str, ...]
    ) -> bool:
        if not user_ids:
            return False
        async with self._session_factory() as session:
            receipts = tuple(
                (
                    await session.scalars(
                        select(SnapshotSeriesPublicationReceiptModel).where(
                            SnapshotSeriesPublicationReceiptModel.job_id == operation_id,
                            SnapshotSeriesPublicationReceiptModel.generation_id == generation_id,
                            SnapshotSeriesPublicationReceiptModel.user_id.in_(user_ids),
                        )
                    )
                ).all()
            )
            return {item.user_id for item in receipts} == set(user_ids)

    async def retire_user(self, user_id: str, *, job_created_at: datetime) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                pointer = await session.get(
                    UserReadModelPublicationModel, user_id, with_for_update=True
                )
                watermark = await session.get(
                    UserReadModelPublicationWatermarkModel,
                    user_id,
                    with_for_update=True,
                )
                if watermark is not None and watermark.causal_at >= job_created_at:
                    return
                if pointer is not None:
                    await session.execute(
                        delete(UserReadModelPublicationModel).where(
                            UserReadModelPublicationModel.user_id == user_id
                        )
                    )
                updated_at = datetime.now(UTC).replace(tzinfo=None)
                if watermark is None:
                    session.add(
                        UserReadModelPublicationWatermarkModel(
                            user_id=user_id,
                            causal_at=job_created_at,
                            kind="retired",
                            generation_id=None,
                            updated_at=updated_at,
                        )
                    )
                else:
                    watermark.causal_at = job_created_at
                    watermark.kind = "retired"
                    watermark.generation_id = None
                    watermark.updated_at = updated_at
        except SQLAlchemyError:
            raise

    async def publish(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        for attempt in range(_PUBLICATION_TRANSACTION_ATTEMPTS):
            try:
                await self._publish_once(manifest)
                return
            except DBAPIError as exc:
                if (
                    getattr(exc.orig, "sqlstate", None) not in _RETRYABLE_PUBLICATION_SQLSTATES
                    or attempt + 1 == _PUBLICATION_TRANSACTION_ATTEMPTS
                ):
                    raise
        raise AssertionError("unreachable")

    async def _publish_once(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            if not manifest.user_projections:
                raise _fail()
            user_ids = tuple(sorted({item.user_id for item in manifest.user_projections}))
            locked_users = tuple(
                await session.scalars(
                    select(UserModel)
                    .where(UserModel.id.in_(user_ids))
                    .order_by(UserModel.id)
                    .with_for_update()
                )
            )
            if {item.id for item in locked_users} != set(user_ids):
                raise _fail()
            users_by_id = {item.id: item for item in locked_users}
            # Use the scheduler's User -> Job order. The worker heartbeat
            # renews the job row, so acquiring both fences before manifest or
            # receipt reads avoids a late snapshot conflict and a scheduler /
            # publisher lock cycle. Heartbeat renewal may wait only for the
            # short atomic switch.
            staged_job = (
                await session.get(
                    SnapshotSeriesRebuildJobModel,
                    manifest.staged_by_job_id,
                    with_for_update=True,
                )
                if manifest.staged_by_job_id is not None
                else None
            )
            receipts = tuple(
                await session.scalars(
                    select(SnapshotSeriesPublicationReceiptModel).where(
                        SnapshotSeriesPublicationReceiptModel.generation_id
                        == manifest.generation_id
                    )
                )
            )
            if (
                receipts
                and {item.user_id for item in receipts}
                == {item.user_id for item in manifest.user_projections}
                and all(
                    item.job_id == (manifest.staged_by_job_id or manifest.job_id)
                    for item in receipts
                )
            ):
                return
            generation = await session.get(
                SnapshotGenerationModel, manifest.generation_id, with_for_update=True
            )
            if generation is None or generation.state != "staged":
                raise _fail()
            await self._verify_exact_manifest(session, manifest)
            await self._verify_live_canonical_boundaries(session, manifest)
            await self._verify_causal_watermarks(session, manifest)
            published_at = datetime.now(UTC).replace(tzinfo=None)
            by_user: dict[str, list[StagedUserSnapshotSeriesProjection]] = {}
            for projection in manifest.user_projections:
                by_user.setdefault(projection.user_id, []).append(projection)
            for user_id, projections in sorted(by_user.items()):
                await publish_snapshot_baselines(
                    session,
                    user_id=user_id,
                    baseline_ids=tuple(item.baseline_id for item in projections),
                    operation_id=manifest.staged_by_job_id or manifest.job_id,
                    published_at=published_at,
                    causal_at=manifest.causal_at,
                    replace_from=manifest.replace_from,
                    dirty_epoch=manifest.dirty_epoch,
                    staged_lease=(
                        manifest.staged_lease_version,
                        manifest.staged_lease_owner,
                    )
                    if manifest.staged_by_job_id is not None
                    else None,
                    locked_user=users_by_id[user_id],
                    locked_staged_job=staged_job,
                )

    async def _verify_live_canonical_boundaries(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        """Reject a staged calculation once any input account has advanced."""

        expected_by_account: dict[str, tuple[int, int | None, int | None]] = {}
        for entry in manifest.account_snapshots:
            account_id = entry.projection.snapshot.account_id
            boundary = (
                entry.canonical_revision,
                entry.investment_revision,
                entry.holding_revision,
            )
            previous = expected_by_account.setdefault(account_id, boundary)
            if previous != boundary:
                raise _fail()
        states = tuple(
            (
                await session.scalars(
                    select(AccountCanonicalStateModel)
                    .where(AccountCanonicalStateModel.account_id.in_(expected_by_account))
                    .order_by(AccountCanonicalStateModel.account_id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        if {state.account_id for state in states} != set(expected_by_account):
            raise _fail()
        for state in states:
            canonical, investment, holding = expected_by_account[state.account_id]
            if state.last_revision != canonical or state.holding_revision != holding:
                raise _fail()
            if investment is None:
                if state.last_investment_revision != 0:
                    raise _fail()
            elif state.last_investment_revision != investment:
                raise _fail()

    async def _verify_causal_watermarks(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        """A durable tombstone or newer publication fences delayed attempts."""
        user_ids = {projection.user_id for projection in manifest.user_projections}
        watermarks = tuple(
            (
                await session.scalars(
                    select(UserReadModelPublicationWatermarkModel)
                    .where(UserReadModelPublicationWatermarkModel.user_id.in_(user_ids))
                    .order_by(UserReadModelPublicationWatermarkModel.user_id)
                    .with_for_update()
                )
            ).all()
        )
        for watermark in watermarks:
            if watermark.causal_at > manifest.causal_at or (
                watermark.causal_at == manifest.causal_at
                and (
                    watermark.kind != "published"
                    or watermark.generation_id != manifest.generation_id
                )
            ):
                raise SnapshotSeriesPublicationSupersededError()

    async def _verify_exact_manifest(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        expected_accounts = {
            entry.projection.snapshot.id: entry for entry in manifest.account_snapshots
        }
        expected_users = {
            (item.user_id, item.timestamp, item.output_currency, item.granularity): item
            for item in manifest.user_projections
        }
        if len(expected_accounts) != len(manifest.account_snapshots) or len(expected_users) != len(
            manifest.user_projections
        ):
            raise _fail()
        targets = tuple(
            (
                await session.scalars(
                    select(SnapshotGenerationTargetModel)
                    .where(SnapshotGenerationTargetModel.generation_id == manifest.generation_id)
                    .order_by(SnapshotGenerationTargetModel.user_id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        if {target.user_id for target in targets} != {
            item.user_id for item in manifest.user_projections
        }:
            raise _fail()
        accounts = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.generation_id == manifest.generation_id)
                    .order_by(AccountSnapshotModel.id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        if {row.id for row in accounts} != set(expected_accounts):
            raise _fail()
        for row in accounts:
            entry = expected_accounts[row.id]
            if not _same_model_values(row, entry.projection.snapshot.model_values()):
                raise _fail()
            items = tuple(
                (
                    await session.scalars(
                        select(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id == row.id)
                        .order_by(AccountSnapshotItemModel.listing_id, AccountSnapshotItemModel.id)
                    )
                ).all()
            )
            expected_items = tuple(item.model_values() for item in entry.projection.items)
            if len(items) != len(expected_items) or any(
                not _same_model_values(item, expected)
                for item, expected in zip(items, expected_items, strict=True)
            ):
                raise _fail()
            boundary = await session.get(AccountSnapshotCanonicalBoundaryModel, row.id)
            expected_boundary = {
                "snapshot_id": row.id,
                "account_id": row.account_id,
                "canonical_revision": entry.canonical_revision,
                "investment_revision": entry.investment_revision,
                "holding_revision": entry.holding_revision,
                "selected_liability_balance_id": entry.selected_liability_balance_id,
                "created_at": row.created_at,
            }
            if boundary is None or not _same_model_values(boundary, expected_boundary):
                raise _fail()
        portfolios = tuple(
            (
                await session.scalars(
                    select(PortfolioSnapshotModel).where(
                        PortfolioSnapshotModel.generation_id == manifest.generation_id
                    )
                )
            ).all()
        )
        net_worths = tuple(
            (
                await session.scalars(
                    select(NetWorthSnapshotModel).where(
                        NetWorthSnapshotModel.generation_id == manifest.generation_id
                    )
                )
            ).all()
        )
        baselines = tuple(
            (
                await session.scalars(
                    select(DailySnapshotBaselineModel).where(
                        DailySnapshotBaselineModel.generation_id == manifest.generation_id
                    )
                )
            ).all()
        )
        for rows, field in (
            (portfolios, "portfolio_snapshot_id"),
            (net_worths, "net_worth_snapshot_id"),
            (baselines, "baseline_id"),
        ):
            if {row.id for row in rows} != {
                getattr(item, field) for item in expected_users.values()
            }:
                raise _fail()
        for expected in expected_users.values():
            portfolio = next(
                (row for row in portfolios if row.id == expected.portfolio_snapshot_id), None
            )
            net_worth = next(
                (row for row in net_worths if row.id == expected.net_worth_snapshot_id), None
            )
            baseline = next((row for row in baselines if row.id == expected.baseline_id), None)
            if (
                portfolio is None
                or net_worth is None
                or baseline is None
                or portfolio.user_id != expected.user_id
                or portfolio.timestamp != expected.timestamp
                or portfolio.currency != expected.output_currency
                or portfolio.granularity is not expected.granularity
                or net_worth.user_id != expected.user_id
                or net_worth.timestamp != expected.timestamp
                or net_worth.currency != expected.output_currency
                or net_worth.granularity is not expected.granularity
                or baseline.user_id != expected.user_id
                or baseline.net_worth_snapshot_id != expected.net_worth_snapshot_id
                or baseline.timestamp != expected.timestamp
                or baseline.currency != expected.output_currency
                or baseline.granularity is not expected.granularity
            ):
                raise _fail()
            children = tuple(
                (
                    await session.scalars(
                        select(DailySnapshotBaselineAccountModel)
                        .where(
                            DailySnapshotBaselineAccountModel.baseline_id == expected.baseline_id
                        )
                        .order_by(DailySnapshotBaselineAccountModel.account_id)
                    )
                ).all()
            )
            if tuple(item.primary_snapshot_id for item in children) != tuple(
                item.snapshot_id for item in expected.output_account_snapshots
            ) or tuple(item.presentation_snapshot_id for item in children) != tuple(
                item.snapshot_id for item in expected.native_account_snapshots
            ):
                raise _fail()

    async def _verify_published_pointers(
        self, session: AsyncSession, manifest: SnapshotSeriesPublicationManifest
    ) -> None:
        latest_by_user: dict[str, StagedUserSnapshotSeriesProjection] = {}
        for projection in manifest.user_projections:
            current = latest_by_user.get(projection.user_id)
            if current is None or projection.timestamp > current.timestamp:
                latest_by_user[projection.user_id] = projection
        for projection in latest_by_user.values():
            pointer = await session.get(
                UserReadModelPublicationModel, projection.user_id, with_for_update=True
            )
            if (
                pointer is None
                or pointer.generation_id != manifest.generation_id
                or pointer.generation_state != "published"
                or pointer.baseline_id != projection.baseline_id
                or pointer.scopes != _SCOPES
            ):
                raise _fail()
