"""Durable rebuild executor composing H2/H4/H5/H7 behind the H3 lease."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.canonical_lineage import (
    UserReadModelPublicationWatermarkModel,
)
from app.db.models.enums import BackgroundJobStatus, SnapshotSeriesJobKind
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesCanonicalInvalidationModel,
    SnapshotSeriesDirtyStateModel,
    SnapshotSeriesRebuildJobModel,
    SnapshotSeriesScheduleStateModel,
)
from app.db.models.snapshot_series_publication import SnapshotSeriesPublicationReceiptModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.jobs.lifecycle import LeaseIdentity
from app.modules.market_data.history.models import HistoricalMarketEvidenceStateError
from app.modules.market_data.models import MarketEvidenceConflictError, MarketEvidenceStateError
from app.modules.market_data.source_policy import MarketEvidenceSourcePolicy
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    exchange_rate_id,
    price_snapshot_id,
)
from app.modules.portfolio_history.builder.market import (
    HistoricalMarketAcquirer,
    HistoricalMarketLookbackUnavailableError,
    HistoricalMarketSelection,
    SelectedHistoricalMetricRate,
    SelectedHistoricalPrice,
    SelectedHistoricalRate,
    SelectedHistoricalSnapshotRate,
)
from app.modules.portfolio_history.builder.planning import (
    HistoryGenerationBuildError,
    build_rebuild_generation_plan,
)
from app.modules.portfolio_history.builder.replay_matrix import replay_accounts_at
from app.modules.portfolio_history.jobs.models import (
    HistoryCapturePayload,
    HistoryRebuildPayload,
    PortfolioHistoryJobCheckpoint,
    PortfolioHistoryJobPhase,
    PortfolioHistoryJobProgress,
    PortfolioHistoryJobResult,
    PortfolioHistoryPublicationRetirementReceipt,
    validate_history_payload,
)
from app.modules.portfolio_history.jobs.repository import ClaimedPortfolioHistoryJob
from app.modules.portfolio_history.jobs.worker import (
    PermanentPortfolioHistoryJobError,
    RetryablePortfolioHistoryJobError,
)
from app.modules.portfolio_history.lattice import HistoryResolution, history_bucket
from app.modules.portfolio_history_rebuild.repository import (
    FrozenPortfolioReplayInput,
    PortfolioHistoryReplayRepository,
    PortfolioHistoryReplayRepositoryError,
)
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.history_series_bridge import (
    HistorySnapshotSeriesBridgeError,
    build_history_snapshot_series_materialization_input,
)
from app.modules.snapshot_refresh.history_series_materializer import (
    SnapshotHistorySeriesMaterializationError,
    materialize_history_snapshot_series,
)
from app.modules.snapshot_refresh.series_executor import (
    ExecuteSnapshotSeriesCommand,
    SnapshotSeriesExecutionStateError,
    SnapshotSeriesPublicationSupersededError,
    generation_id_for_job,
)
from app.modules.snapshots.account_projection import AccountSnapshotProjectionStateError

_GENERATION_NAMESPACE = UUID("20bf5cb8-bc69-4496-86fc-2e12f896eaa7")
_MILLISECOND = timedelta(milliseconds=1)
_MINUTE = timedelta(minutes=1)
_MARKET_IDENTITY_QUERY_CHUNK = 500
logger = logging.getLogger(__name__)
type CheckpointCallback = Callable[
    [PortfolioHistoryJobCheckpoint, PortfolioHistoryJobProgress], Awaitable[None]
]
type ScopeLoader = Callable[[str], Awaitable[FrozenPortfolioReplayInput]]
type OperationalClock = Callable[[], datetime]


class _SnapshotSeriesExecutor(Protocol):
    async def execute(self, command: ExecuteSnapshotSeriesCommand) -> object: ...

    async def retire_user(self, user_id: str, *, job_created_at: datetime) -> None: ...


def _utc_now() -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)


def _operation_timestamp(clock: OperationalClock) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is not None or value.microsecond % 1_000:
        raise ValueError("History builder operational clock is invalid.")
    return value


def _ceil_snapshot_minute(value: datetime) -> datetime:
    """Return the first minute boundary that is not earlier than the event."""

    if value.second == 0 and value.microsecond == 0:
        return value
    return value.replace(second=0, microsecond=0) + _MINUTE


def _superseded_job_error(cause: str) -> PermanentPortfolioHistoryJobError:
    return PermanentPortfolioHistoryJobError(
        code=f"history_{cause}_superseded",
        message="A newer publication superseded this history job.",
    )


def _reconcile_historical_market_selection(
    selection: HistoricalMarketSelection,
    *,
    persisted_prices: tuple[PriceSnapshotModel, ...],
    persisted_rates: tuple[ExchangeRateModel, ...],
) -> HistoricalMarketSelection:
    """Make persisted immutable evidence authoritative for identical provider identities."""

    prices_by_key = {
        (item.listing_id, item.timestamp, item.source): item for item in persisted_prices
    }
    rates_by_key = {
        (item.from_currency, item.to_currency, item.date, item.source): item
        for item in persisted_rates
    }
    canonical_prices: dict[str, PriceObservation] = {}
    for observation in selection.price_observations:
        persisted = prices_by_key.get(
            (observation.listing_id, observation.observed_at, observation.provider)
        )
        if persisted is None:
            canonical = observation
        else:
            canonical = PriceObservation(
                asset_id=persisted.asset_id,
                listing_id=persisted.listing_id,
                provider=persisted.source,
                provider_symbol=observation.provider_symbol,
                price=persisted.price,
                currency=persisted.currency,
                observed_at=persisted.timestamp,
            )
            if (
                persisted.id != price_snapshot_id(canonical)
                or canonical.asset_id != observation.asset_id
                or canonical.currency != observation.currency
            ):
                raise MarketEvidenceConflictError()
        canonical_prices[price_snapshot_id(observation)] = canonical

    canonical_rates: dict[str, ExchangeRateObservation] = {}
    for rate_observation in selection.rate_observations:
        persisted_rate = rates_by_key.get(
            (
                rate_observation.from_currency,
                rate_observation.to_currency,
                rate_observation.effective_at,
                rate_observation.provider,
            )
        )
        if persisted_rate is None:
            canonical_rate_observation = rate_observation
        else:
            canonical_rate_observation = ExchangeRateObservation(
                from_currency=persisted_rate.from_currency,
                to_currency=persisted_rate.to_currency,
                provider=persisted_rate.source,
                rate=persisted_rate.rate,
                effective_at=persisted_rate.date,
            )
            if persisted_rate.id != exchange_rate_id(canonical_rate_observation):
                raise MarketEvidenceConflictError()
        canonical_rates[exchange_rate_id(rate_observation)] = canonical_rate_observation

    def canonical_price(item: SelectedHistoricalPrice) -> SelectedHistoricalPrice:
        observation = canonical_prices.get(item.price_id)
        if observation is None:
            raise MarketEvidenceConflictError()
        return SelectedHistoricalPrice(
            account_id=item.account_id,
            through=item.through,
            listing=item.listing,
            price_id=item.price_id,
            observation=observation,
        )

    def selected_canonical_rate(item: SelectedHistoricalRate) -> SelectedHistoricalRate:
        observation = canonical_rates.get(item.rate_id)
        if observation is None:
            raise MarketEvidenceConflictError()
        return SelectedHistoricalRate(
            account_id=item.account_id,
            through=item.through,
            rate_id=item.rate_id,
            observation=observation,
            consumed=item.consumed,
        )

    def canonical_snapshot_rate(
        item: SelectedHistoricalSnapshotRate,
    ) -> SelectedHistoricalSnapshotRate:
        observation = canonical_rates.get(item.rate_id)
        if observation is None:
            raise MarketEvidenceConflictError()
        return SelectedHistoricalSnapshotRate(
            account_id=item.account_id,
            through=item.through,
            output_currency=item.output_currency,
            rate_id=item.rate_id,
            observation=observation,
        )

    def canonical_metric_rate(
        item: SelectedHistoricalMetricRate,
    ) -> SelectedHistoricalMetricRate:
        observation = canonical_rates.get(item.rate_id)
        if observation is None:
            raise MarketEvidenceConflictError()
        return SelectedHistoricalMetricRate(
            account_id=item.account_id,
            evidence_id=item.evidence_id,
            event_at=item.event_at,
            output_currency=item.output_currency,
            rate_id=item.rate_id,
            observation=observation,
        )

    return HistoricalMarketSelection(
        prices=tuple(canonical_price(item) for item in selection.prices),
        rates=tuple(selected_canonical_rate(item) for item in selection.rates),
        price_observations=tuple(
            canonical_prices[price_snapshot_id(item)] for item in selection.price_observations
        ),
        rate_observations=tuple(
            canonical_rates[exchange_rate_id(item)] for item in selection.rate_observations
        ),
        provider_call_count=selection.provider_call_count,
        snapshot_rates=tuple(canonical_snapshot_rate(item) for item in selection.snapshot_rates),
        metric_rates=tuple(canonical_metric_rate(item) for item in selection.metric_rates),
    )


class _SnapshotSeriesPersistence(Protocol):
    async def has_receipt(self, *, user_id: str, job_id: str, generation_id: str) -> bool: ...

    async def write_market(
        self, *, selection: HistoricalMarketSelection, now: datetime
    ) -> HistoricalMarketSelection: ...

    async def finalize(
        self,
        *,
        user_id: str,
        job_id: str,
        lease: LeaseIdentity,
        generation_id: str,
        dirty_epoch: int | None,
        capture_at: datetime | None,
        rebuild_covered_through: datetime | None,
        now: datetime,
    ) -> None: ...

    async def finalize_empty(
        self,
        *,
        user_id: str,
        job_id: str,
        lease: LeaseIdentity,
        dirty_epoch: int,
        causal_at: datetime,
        now: datetime,
    ) -> None: ...


class DatabaseSnapshotSeriesPersistence:
    """Persist market evidence and lease-fence post-publication finalization."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def has_receipt(self, *, user_id: str, job_id: str, generation_id: str) -> bool:
        async with self.session_factory() as session:
            receipt_id = await session.scalar(
                select(SnapshotSeriesPublicationReceiptModel.id).where(
                    SnapshotSeriesPublicationReceiptModel.user_id == user_id,
                    SnapshotSeriesPublicationReceiptModel.job_id == job_id,
                    SnapshotSeriesPublicationReceiptModel.generation_id == generation_id,
                )
            )
            return receipt_id is not None

    async def write_market(
        self, *, selection: HistoricalMarketSelection, now: datetime
    ) -> HistoricalMarketSelection:
        selection = await self._reconcile_market(selection)
        async with self.session_factory() as session:
            await MarketEvidenceWriter(session).write(
                PersistMarketEvidenceCommand(
                    price_observations=selection.price_observations,
                    exchange_rate_observations=selection.rate_observations,
                    created_at=now,
                )
            )
        return selection

    async def _reconcile_market(
        self, selection: HistoricalMarketSelection
    ) -> HistoricalMarketSelection:
        price_keys = tuple(
            (item.listing_id, item.observed_at, item.provider)
            for item in selection.price_observations
        )
        rate_keys = tuple(
            (item.from_currency, item.to_currency, item.effective_at, item.provider)
            for item in selection.rate_observations
        )
        persisted_prices: list[PriceSnapshotModel] = []
        persisted_rates: list[ExchangeRateModel] = []
        async with self.session_factory() as session:
            for index in range(0, len(price_keys), _MARKET_IDENTITY_QUERY_CHUNK):
                price_chunk = price_keys[index : index + _MARKET_IDENTITY_QUERY_CHUNK]
                persisted_prices.extend(
                    (
                        await session.scalars(
                            select(PriceSnapshotModel).where(
                                tuple_(
                                    PriceSnapshotModel.listing_id,
                                    PriceSnapshotModel.timestamp,
                                    PriceSnapshotModel.source,
                                ).in_(price_chunk)
                            )
                        )
                    ).all()
                )
            for index in range(0, len(rate_keys), _MARKET_IDENTITY_QUERY_CHUNK):
                rate_chunk = rate_keys[index : index + _MARKET_IDENTITY_QUERY_CHUNK]
                persisted_rates.extend(
                    (
                        await session.scalars(
                            select(ExchangeRateModel).where(
                                tuple_(
                                    ExchangeRateModel.from_currency,
                                    ExchangeRateModel.to_currency,
                                    ExchangeRateModel.date,
                                    ExchangeRateModel.source,
                                ).in_(rate_chunk)
                            )
                        )
                    ).all()
                )
        return _reconcile_historical_market_selection(
            selection,
            persisted_prices=tuple(persisted_prices),
            persisted_rates=tuple(persisted_rates),
        )

    async def finalize(
        self,
        *,
        user_id: str,
        job_id: str,
        lease: LeaseIdentity,
        generation_id: str,
        dirty_epoch: int | None,
        capture_at: datetime | None,
        rebuild_covered_through: datetime | None,
        now: datetime,
    ) -> None:
        if (dirty_epoch is None) != (rebuild_covered_through is None):
            raise SnapshotSeriesExecutionStateError()
        async with self.session_factory() as session, session.begin():
            job = await session.scalar(
                select(SnapshotSeriesRebuildJobModel)
                .where(
                    SnapshotSeriesRebuildJobModel.id == job_id,
                    SnapshotSeriesRebuildJobModel.user_id == user_id,
                )
                .with_for_update()
            )
            receipt = await session.scalar(
                select(SnapshotSeriesPublicationReceiptModel).where(
                    SnapshotSeriesPublicationReceiptModel.user_id == user_id,
                    SnapshotSeriesPublicationReceiptModel.job_id == job_id,
                    SnapshotSeriesPublicationReceiptModel.generation_id == generation_id,
                )
            )
            if (
                job is None
                or job.status is not BackgroundJobStatus.running
                or job.lease_owner != lease.owner
                or job.lease_version != lease.version
                or lease.job_id != job_id
                or receipt is None
            ):
                raise SnapshotSeriesExecutionStateError()
            if dirty_epoch is not None:
                dirty = await session.scalar(
                    select(SnapshotSeriesDirtyStateModel)
                    .where(SnapshotSeriesDirtyStateModel.user_id == user_id)
                    .with_for_update()
                )
                receipts = tuple(
                    await session.scalars(
                        select(SnapshotSeriesCanonicalInvalidationModel)
                        .where(
                            SnapshotSeriesCanonicalInvalidationModel.user_id == user_id,
                            SnapshotSeriesCanonicalInvalidationModel.first_dirty_epoch
                            <= dirty_epoch,
                            SnapshotSeriesCanonicalInvalidationModel.resolved_at.is_(None),
                        )
                        .with_for_update()
                    )
                )
                if dirty is not None and dirty.dirty_epoch == dirty_epoch:
                    for invalidation in receipts:
                        invalidation.resolved_at = now
                        invalidation.resolved_snapshot_generation_id = generation_id
                    await session.delete(dirty)
            if rebuild_covered_through is not None:
                schedule = await session.scalar(
                    select(SnapshotSeriesScheduleStateModel)
                    .where(SnapshotSeriesScheduleStateModel.user_id == user_id)
                    .with_for_update()
                )
                if schedule is not None:
                    _advance_rebuild_schedule(
                        schedule,
                        covered_through=rebuild_covered_through,
                        now=now,
                    )
            if capture_at is not None:
                schedule = await session.scalar(
                    select(SnapshotSeriesScheduleStateModel)
                    .where(SnapshotSeriesScheduleStateModel.user_id == user_id)
                    .with_for_update()
                )
                if (
                    schedule is not None
                    and schedule.next_capture_at == capture_at
                    and (
                        schedule.last_captured_bucket is None
                        or schedule.last_captured_bucket < capture_at
                    )
                ):
                    schedule.last_captured_bucket = capture_at
                    schedule.next_capture_at = history_bucket(
                        capture_at, HistoryResolution.minutes_30
                    ).end
                    schedule.updated_at = now

    async def finalize_empty(
        self,
        *,
        user_id: str,
        job_id: str,
        lease: LeaseIdentity,
        dirty_epoch: int,
        causal_at: datetime,
        now: datetime,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            job = await session.scalar(
                select(SnapshotSeriesRebuildJobModel)
                .where(
                    SnapshotSeriesRebuildJobModel.id == job_id,
                    SnapshotSeriesRebuildJobModel.user_id == user_id,
                )
                .with_for_update()
            )
            watermark = await session.scalar(
                select(UserReadModelPublicationWatermarkModel)
                .where(UserReadModelPublicationWatermarkModel.user_id == user_id)
                .with_for_update()
            )
            if (
                job is None
                or job.status is not BackgroundJobStatus.running
                or job.lease_owner != lease.owner
                or job.lease_version != lease.version
                or lease.job_id != job_id
                or watermark is None
                or watermark.causal_at != causal_at
                or watermark.kind != "retired"
            ):
                raise SnapshotSeriesExecutionStateError()
            dirty = await session.scalar(
                select(SnapshotSeriesDirtyStateModel)
                .where(SnapshotSeriesDirtyStateModel.user_id == user_id)
                .with_for_update()
            )
            receipts = tuple(
                await session.scalars(
                    select(SnapshotSeriesCanonicalInvalidationModel)
                    .where(
                        SnapshotSeriesCanonicalInvalidationModel.user_id == user_id,
                        SnapshotSeriesCanonicalInvalidationModel.first_dirty_epoch <= dirty_epoch,
                        SnapshotSeriesCanonicalInvalidationModel.resolved_at.is_(None),
                    )
                    .with_for_update()
                )
            )
            if dirty is not None and dirty.dirty_epoch == dirty_epoch:
                for receipt in receipts:
                    receipt.resolved_at = now
                    receipt.resolved_snapshot_generation_id = None
                await session.delete(dirty)


def _covered_through(job_created_at: datetime) -> datetime:
    # A rebuild may be enqueued anywhere inside the current 30-minute capture
    # bucket. Its market range must never extend to that bucket's future end.
    # The scheduler-owned capture path remains responsible for complete
    # 30-minute boundaries.
    return job_created_at.replace(second=0, microsecond=0)


def _advance_rebuild_schedule(
    schedule: SnapshotSeriesScheduleStateModel,
    *,
    covered_through: datetime,
    now: datetime,
) -> None:
    bucket = history_bucket(covered_through, HistoryResolution.minutes_30)
    if schedule.next_capture_at >= bucket.end:
        return
    if schedule.last_captured_bucket is None or schedule.last_captured_bucket < bucket.start:
        schedule.last_captured_bucket = bucket.start
    schedule.next_capture_at = bucket.end
    schedule.updated_at = now


def _generation_id(*, cause: str, job_id: str, started_at: object) -> str:
    """Keep one worker run idempotent while separating a later scheduled retry."""

    seed = f"{cause}\0{job_id}"
    if isinstance(started_at, datetime):
        seed = f"{seed}\0{started_at.isoformat()}"
    return str(uuid5(_GENERATION_NAMESPACE, seed))


class RebuildPortfolioHistoryJobExecutor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        source_policy: MarketEvidenceSourcePolicy,
        market_acquirer: HistoricalMarketAcquirer,
        calculation_version: int,
        persistence: _SnapshotSeriesPersistence | None = None,
        scope_loader: ScopeLoader | None = None,
        snapshot_series_executor: _SnapshotSeriesExecutor | None = None,
        clock: OperationalClock = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.source_policy = source_policy
        self.market_acquirer = market_acquirer
        self.calculation_version = calculation_version
        self.persistence = persistence or DatabaseSnapshotSeriesPersistence(session_factory)
        self.scope_loader = scope_loader
        if snapshot_series_executor is None:
            raise ValueError("Snapshot-series executor is required.")
        self.snapshot_series_executor = snapshot_series_executor
        self.clock = clock

    async def _scope(self, user_id: str) -> FrozenPortfolioReplayInput:
        if self.scope_loader is not None:
            return await self.scope_loader(user_id)
        async with self.session_factory() as session, session.begin():
            return await PortfolioHistoryReplayRepository(
                session, source_policy=self.source_policy
            ).load_frozen_scope(user_id=user_id)

    async def execute(
        self,
        claimed: ClaimedPortfolioHistoryJob,
        *,
        checkpoint: CheckpointCallback,
    ) -> PortfolioHistoryJobResult:
        job = claimed.job
        if job.kind not in {
            SnapshotSeriesJobKind.rebuild,
            SnapshotSeriesJobKind.capture,
        }:
            raise PermanentPortfolioHistoryJobError(
                code="history_job_kind_not_configured",
                message="This history job kind is not configured.",
            )
        payload = validate_history_payload(job.kind, job.payload)
        if not isinstance(payload, (HistoryRebuildPayload, HistoryCapturePayload)):
            raise PermanentPortfolioHistoryJobError(
                code="history_job_payload_invalid",
                message="The history job request is invalid.",
            )
        try:
            operation_at = _operation_timestamp(self.clock)
        except ValueError as exc:
            raise PermanentPortfolioHistoryJobError(
                code="history_job_clock_invalid",
                message="The history job operational clock is invalid.",
            ) from exc
        materialization_at = getattr(job, "started_at", None)
        if (
            type(materialization_at) is not datetime
            or materialization_at.tzinfo is not None
            or materialization_at.microsecond % 1_000
        ):
            raise PermanentPortfolioHistoryJobError(
                code="history_job_started_at_invalid",
                message="The history job start timestamp is invalid.",
            )
        saved = PortfolioHistoryJobCheckpoint.model_validate(job.checkpoint)
        cause = "rebuild" if isinstance(payload, HistoryRebuildPayload) else "capture"
        derived_generation_id = _generation_id(
            cause=cause,
            job_id=job.id,
            started_at=getattr(job, "started_at", None),
        )
        if isinstance(payload, HistoryRebuildPayload):
            through = _covered_through(job.created_at)
            phase = PortfolioHistoryJobPhase.replaying
        else:
            capture_bucket = history_bucket(
                payload.capture_at - _MILLISECOND,
                HistoryResolution.minutes_30,
            )
            if capture_bucket.end != payload.capture_at:
                raise PermanentPortfolioHistoryJobError(
                    code="history_job_payload_invalid",
                    message="The history job request is invalid.",
                )
            through = payload.capture_at - _MINUTE
            phase = PortfolioHistoryJobPhase.capturing
        if saved.generation_id is not None and saved.covered_through != through:
            raise PermanentPortfolioHistoryJobError(
                code="history_job_checkpoint_invalid",
                message="The history job checkpoint is invalid.",
            )
        generation_id = saved.generation_id or derived_generation_id
        try:
            published_generation_id = generation_id_for_job(f"{job.id}:{generation_id}")
            if await self.persistence.has_receipt(
                user_id=job.user_id,
                job_id=job.id,
                generation_id=published_generation_id,
            ):
                await self.persistence.finalize(
                    user_id=job.user_id,
                    job_id=job.id,
                    lease=claimed.lease,
                    generation_id=published_generation_id,
                    dirty_epoch=(
                        payload.dirty_epoch if isinstance(payload, HistoryRebuildPayload) else None
                    ),
                    capture_at=(
                        payload.capture_at if isinstance(payload, HistoryCapturePayload) else None
                    ),
                    rebuild_covered_through=(
                        through if isinstance(payload, HistoryRebuildPayload) else None
                    ),
                    now=operation_at,
                )
                return PortfolioHistoryJobResult(completed_at=operation_at, outcome="completed")
            replay_scope = await self._scope(job.user_id)
            if replay_scope.earliest_event_at is None:
                if isinstance(payload, HistoryRebuildPayload):
                    await self.snapshot_series_executor.retire_user(
                        job.user_id,
                        job_created_at=job.created_at,
                    )
                    await self.persistence.finalize_empty(
                        user_id=job.user_id,
                        job_id=job.id,
                        lease=claimed.lease,
                        dirty_epoch=payload.dirty_epoch,
                        causal_at=job.created_at,
                        now=operation_at,
                    )
                    return PortfolioHistoryJobResult(
                        completed_at=operation_at,
                        outcome="no_work",
                        retirement=PortfolioHistoryPublicationRetirementReceipt(
                            retired_at=operation_at
                        ),
                    )
                return PortfolioHistoryJobResult(completed_at=operation_at, outcome="no_work")
            await checkpoint(
                PortfolioHistoryJobCheckpoint(
                    phase=phase,
                    completed_units=0,
                    generation_id=generation_id,
                    covered_through=through,
                ),
                PortfolioHistoryJobProgress(
                    phase=phase,
                    completed_units=0,
                    total_units=1,
                ),
            )
            plan = build_rebuild_generation_plan(
                first_event_at=replay_scope.earliest_event_at,
                dirty_from=(
                    payload.dirty_from if isinstance(payload, HistoryRebuildPayload) else through
                ),
                covered_through=through,
                source_policy=self.source_policy,
                subdaily_available_since=(
                    self.market_acquirer.subdaily_available_since(
                        scope=replay_scope,
                        as_of=through,
                    )
                    if isinstance(self.market_acquirer, HistoricalMarketAcquirer)
                    else None
                ),
            )
            series_replay_timestamps = tuple(
                sorted(
                    {_ceil_snapshot_minute(item.representative_at) for item in plan.suffix_buckets}
                )
            )
            replay_timestamps = tuple(sorted({*plan.replay_timestamps, *series_replay_timestamps}))
            all_states = replay_accounts_at(replay_scope, timestamps=replay_timestamps)
            series_states = {
                timestamp: all_states[timestamp] for timestamp in series_replay_timestamps
            }
            series_subdaily_timestamps = tuple(
                sorted({_ceil_snapshot_minute(item) for item in plan.subdaily_market_timestamps})
            )
            selection = await self.market_acquirer.acquire(
                scope=replay_scope,
                states=all_states,
                requested_at=tuple(sorted({*plan.market_timestamps, *series_replay_timestamps})),
                subdaily_at=tuple(
                    sorted({*plan.subdaily_market_timestamps, *series_subdaily_timestamps})
                ),
            )
            selection = await self.persistence.write_market(selection=selection, now=operation_at)
            series_input = build_history_snapshot_series_materialization_input(
                job_id=f"{job.id}:{generation_id}",
                replay_scope=replay_scope,
                states=series_states,
                market=selection,
                calculation_version=self.calculation_version,
                calculated_at=materialization_at,
                created_at=materialization_at,
                causal_at=job.created_at,
            )
            series_command = materialize_history_snapshot_series(series_input)
            result = await self.snapshot_series_executor.execute(
                ExecuteSnapshotSeriesCommand(
                    job_id=series_command.job_id,
                    targets=series_command.targets,
                    points=series_command.points,
                    causal_at=series_command.causal_at,
                    replace_from=(
                        payload.dirty_from if isinstance(payload, HistoryRebuildPayload) else None
                    ),
                    dirty_epoch=(
                        payload.dirty_epoch if isinstance(payload, HistoryRebuildPayload) else None
                    ),
                    staged_by_job_id=job.id,
                    staged_lease_version=claimed.lease.version,
                    staged_lease_owner=claimed.lease.owner,
                )
            )
            result_generation_id = getattr(result, "generation_id", None)
            if not isinstance(result_generation_id, str) or not result_generation_id:
                raise SnapshotSeriesExecutionStateError()
            await self.persistence.finalize(
                user_id=job.user_id,
                job_id=job.id,
                lease=claimed.lease,
                generation_id=result_generation_id,
                dirty_epoch=(
                    payload.dirty_epoch if isinstance(payload, HistoryRebuildPayload) else None
                ),
                capture_at=(
                    payload.capture_at if isinstance(payload, HistoryCapturePayload) else None
                ),
                rebuild_covered_through=(
                    through if isinstance(payload, HistoryRebuildPayload) else None
                ),
                now=operation_at,
            )
        except HistoricalMarketLookbackUnavailableError as exc:
            raise PermanentPortfolioHistoryJobError(
                code="history_source_lookback_unavailable",
                message="Historical provider data does not cover this period; change the source or history range.",
            ) from exc
        except SnapshotSeriesPublicationSupersededError as exc:
            raise _superseded_job_error(cause) from exc
        except MarketEvidenceConflictError as exc:
            raise RetryablePortfolioHistoryJobError(
                code="history_market_evidence_conflict",
                message="Historical market evidence conflicts with persisted state.",
            ) from exc
        except HistoricalMarketEvidenceStateError as exc:
            logger.exception(
                "portfolio_history_market_evidence_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise RetryablePortfolioHistoryJobError(
                code="history_evidence_unavailable",
                message="Historical evidence is temporarily unavailable.",
            ) from exc
        except PortfolioHistoryReplayRepositoryError as exc:
            raise RetryablePortfolioHistoryJobError(
                code="history_replay_input_unavailable",
                message="Canonical history input is temporarily unavailable.",
            ) from exc
        except MarketEvidenceStateError as exc:
            raise RetryablePortfolioHistoryJobError(
                code="history_market_identity_unavailable",
                message="Historical market identity is temporarily unavailable.",
            ) from exc
        except AccountSnapshotProjectionStateError as exc:
            raise RetryablePortfolioHistoryJobError(
                code="history_valuation_evidence_invalid",
                message="Historical valuation evidence is temporarily invalid.",
            ) from exc
        except (
            HistorySnapshotSeriesBridgeError,
            SnapshotHistorySeriesMaterializationError,
            SnapshotSeriesExecutionStateError,
        ) as exc:
            logger.exception(
                "portfolio_history_snapshot_series_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise RetryablePortfolioHistoryJobError(
                code="history_snapshot_series_unavailable",
                message="Historical snapshot publication is temporarily unavailable.",
            ) from exc
        except HistoryGenerationBuildError as exc:
            logger.exception(
                "portfolio_history_generation_build_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise RetryablePortfolioHistoryJobError(
                code="history_evidence_unavailable",
                message="Historical evidence is temporarily unavailable.",
            ) from exc
        return PortfolioHistoryJobResult(completed_at=operation_at, outcome="completed")


__all__ = [
    "DatabaseSnapshotSeriesPersistence",
    "RebuildPortfolioHistoryJobExecutor",
]
