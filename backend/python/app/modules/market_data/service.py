"""Orchestrate exact planning, provider I/O, validation, and atomic persistence."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ExchangeRateSource, MarketDataFailureReason, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.exchange_calendar import assess_market
from app.modules.market_data.health import ListingHealthOutcome
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceRefreshResult,
    MarketEvidenceStateError,
    PriceIdentityFailure,
    PriceRequirement,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.market_data.provider_failure import ProviderFailure
from app.modules.market_data.providers import (
    BatchExchangeRateProvider,
    ExchangeRateProviderRegistry,
    PriceProviderRegistry,
)
from app.modules.market_data.requirements import (
    BuildMarketEvidenceRefreshPlanCommand,
    MarketEvidenceRequirementsPlanner,
)
from app.modules.market_data.requirements_repository import (
    MarketEvidenceRequirementsRepository,
)
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    PersistMarketEvidenceResult,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshMarketEvidenceCommand:
    user_id: str
    snapshot_timestamp: datetime
    created_at: datetime
    reuse_persisted_fx_on_conflict: bool = False


class _Planner(Protocol):
    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan: ...


class _Writer(Protocol):
    async def write(
        self,
        command: PersistMarketEvidenceCommand,
        *,
        transactional_finalize: Callable[[], Awaitable[None]] | None = None,
    ) -> PersistMarketEvidenceResult: ...


class _ReadBoundary(Protocol):
    async def set_transaction_repeatable_read_only(self) -> None: ...


class _HealthCoordinator(Protocol):
    async def claim(
        self,
        *,
        listing_id: str,
        provider: PriceSource,
        provider_symbol: str,
        lease_owner: str,
        now: datetime,
        lease_for: timedelta,
    ) -> bool: ...

    async def record(
        self,
        *,
        listing_id: str,
        provider: PriceSource,
        provider_symbol: str | None,
        outcome: ListingHealthOutcome,
        lease_owner: str | None = None,
    ) -> object | None: ...


_MAX_CONCURRENT_ACQUISITIONS = 4
_UNSET = object()


async def _acquire_bounded[T](
    operations: tuple[Callable[[], Awaitable[T]], ...],
) -> tuple[T, ...]:
    """Run independent provider acquisitions with deterministic result slots.

    A TaskGroup cancels unfinished operations when one raises. Health-enabled
    price operations convert provider failures into result values so sibling
    acquisitions can finish before their outcomes are recorded.
    """

    if not operations:
        return ()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ACQUISITIONS)
    results: list[T | object] = [_UNSET] * len(operations)

    async def _run(index: int, operation: Callable[[], Awaitable[T]]) -> None:
        async with semaphore:
            results[index] = await operation()

    async with asyncio.TaskGroup() as task_group:
        for index, operation in enumerate(operations):
            task_group.create_task(_run(index, operation))
    if any(result is _UNSET for result in results):
        raise _fail()
    return tuple(cast(T, result) for result in results)


@dataclass(frozen=True, slots=True)
class _AcquiredPrice:
    index: int
    observation: PriceObservation


@dataclass(frozen=True, slots=True)
class _FailedPrice:
    index: int
    reason: MarketDataFailureReason
    retry_after: datetime | None = None


@dataclass(frozen=True, slots=True)
class _FailedFx:
    pass


@dataclass(frozen=True, slots=True)
class _AcquiredExchangeRates:
    observations: tuple[tuple[int, ExchangeRateObservation], ...]


type _Acquisition = _AcquiredPrice | _FailedPrice | _AcquiredExchangeRates | _FailedFx


@dataclass(frozen=True, slots=True)
class _ClaimedPrice:
    index: int
    started_at: datetime
    token: str


_HEALTH_LEASE = timedelta(minutes=5)


def _health_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _health_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise _fail()
    return value


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
        raise _fail()
    return result


def _validate_plan(
    value: object,
    *,
    user_id: str,
    snapshot_timestamp: datetime,
    price_registry: PriceProviderRegistry,
    fx_registry: ExchangeRateProviderRegistry,
) -> MarketEvidenceRefreshPlan:
    if (
        not isinstance(value, MarketEvidenceRefreshPlan)
        or value.user_id != _nonblank(user_id)
        or value.snapshot_timestamp != snapshot_timestamp
        or not isinstance(value.price_requirements, tuple)
        or not isinstance(value.fx_requirements, tuple)
        or not isinstance(value.identity_failures, tuple)
    ):
        raise _fail()
    _currency(value.output_currency)
    price_keys: set[tuple[str, object, datetime]] = set()
    for price_requirement in value.price_requirements:
        if (
            not isinstance(price_requirement, PriceRequirement)
            or price_requirement.through != snapshot_timestamp
            or price_requirement.provider not in price_registry.sources
        ):
            raise _fail()
        _nonblank(price_requirement.account_id)
        _nonblank(price_requirement.asset_id)
        listing_id = _nonblank(price_requirement.listing_id)
        _currency(price_requirement.listing_currency)
        _nonblank(price_requirement.provider_symbol)
        price_key = (
            listing_id,
            price_requirement.provider,
            price_requirement.through,
        )
        if price_key in price_keys:
            raise _fail()
        price_keys.add(price_key)
    if value.price_requirements != tuple(
        sorted(
            value.price_requirements,
            key=lambda item: (
                item.account_id,
                item.asset_id,
                item.listing_id,
                item.provider.value,
                item.provider_symbol,
            ),
        )
    ):
        raise _fail()

    failure_keys: set[tuple[str, PriceSource]] = set()
    for identity_failure in value.identity_failures:
        if (
            not isinstance(identity_failure, PriceIdentityFailure)
            or identity_failure.provider not in price_registry.sources
            or identity_failure.reason is not MarketDataFailureReason.missing_provider_symbol
            or not isinstance(identity_failure.configured_at, datetime)
            or identity_failure.configured_at.tzinfo is not None
        ):
            raise _fail()
        key = (_nonblank(identity_failure.listing_id), identity_failure.provider)
        if key in failure_keys:
            raise _fail()
        failure_keys.add(key)
    if value.identity_failures != tuple(
        sorted(
            value.identity_failures,
            key=lambda item: (item.provider.value, item.listing_id),
        )
    ):
        raise _fail()

    fx_keys: set[tuple[str, str, datetime, object]] = set()
    for fx_requirement in value.fx_requirements:
        if (
            not isinstance(fx_requirement, ExchangeRateRequirement)
            or fx_requirement.provider not in fx_registry.sources
        ):
            raise _fail()
        from_currency = _currency(fx_requirement.from_currency)
        to_currency = _currency(fx_requirement.to_currency)
        through = _timestamp(fx_requirement.through)
        fx_key = (
            from_currency,
            to_currency,
            through,
            fx_requirement.provider,
        )
        if from_currency == to_currency or through > snapshot_timestamp or fx_key in fx_keys:
            raise _fail()
        fx_keys.add(fx_key)
    if value.fx_requirements != tuple(
        sorted(
            value.fx_requirements,
            key=lambda item: (
                item.from_currency,
                item.to_currency,
                item.through,
                item.provider.value,
            ),
        )
    ):
        raise _fail()
    return value


def _coalesce_price_observations(
    observations: tuple[PriceObservation, ...],
) -> tuple[PriceObservation, ...]:
    by_identity: dict[tuple[str, datetime, object], PriceObservation] = {}
    for observation in observations:
        if not isinstance(observation, PriceObservation):
            raise _fail()
        identity = (
            observation.listing_id,
            observation.observed_at,
            observation.provider,
        )
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = observation
        elif (
            existing.asset_id,
            existing.listing_id,
            existing.provider,
            existing.provider_symbol,
            existing.price,
            existing.currency,
            existing.observed_at,
        ) != (
            observation.asset_id,
            observation.listing_id,
            observation.provider,
            observation.provider_symbol,
            observation.price,
            observation.currency,
            observation.observed_at,
        ):
            raise _fail()
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (
                item.listing_id,
                item.observed_at,
                item.provider.value,
            ),
        )
    )


def _coalesce_exchange_rate_observations(
    observations: tuple[ExchangeRateObservation, ...],
) -> tuple[ExchangeRateObservation, ...]:
    by_identity: dict[
        tuple[str, str, datetime, object],
        ExchangeRateObservation,
    ] = {}
    for observation in observations:
        if not isinstance(observation, ExchangeRateObservation):
            raise _fail()
        identity = (
            observation.from_currency,
            observation.to_currency,
            observation.effective_at,
            observation.provider,
        )
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = observation
        elif (
            existing.from_currency,
            existing.to_currency,
            existing.provider,
            existing.rate,
            existing.effective_at,
        ) != (
            observation.from_currency,
            observation.to_currency,
            observation.provider,
            observation.rate,
            observation.effective_at,
        ):
            raise _fail()
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (
                item.from_currency,
                item.to_currency,
                item.effective_at,
                item.provider.value,
            ),
        )
    )


class MarketEvidenceRefreshService:
    """Call providers only after an immutable read transaction has closed."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        price_registry: PriceProviderRegistry | None = None,
        fx_registry: ExchangeRateProviderRegistry | None = None,
        fx_source: ExchangeRateSource | None = None,
        source_policy: MarketEvidenceSourcePolicy | None = None,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
        read_boundary: _ReadBoundary | None = None,
        planner: _Planner | None = None,
        writer: _Writer | None = None,
        health: _HealthCoordinator | None = None,
        health_clock: Callable[[], datetime] = _health_now,
        health_token: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self.session = session
        self.price_registry = price_registry or PriceProviderRegistry()
        self.fx_registry = fx_registry or ExchangeRateProviderRegistry()
        self.policy = validate_market_evidence_policy(policy)
        if fx_source is not None and fx_source not in self.fx_registry.sources:
            raise _fail()
        if fx_source is None and len(self.fx_registry.sources) == 1:
            fx_source = next(iter(self.fx_registry.sources))
        if source_policy is not None:
            validated_source_policy = validate_market_evidence_source_policy(source_policy)
            if (
                validated_source_policy.price_sources != self.price_registry.sources
                or validated_source_policy.fx_source is not fx_source
            ):
                raise _fail()
        else:
            validated_source_policy = None
        self.fx_source = fx_source
        self.source_policy = validated_source_policy
        self.read_boundary = read_boundary or MarketEvidenceRequirementsRepository(session)
        self.planner = planner or MarketEvidenceRequirementsPlanner(
            session,
            price_sources=self.price_registry.sources,
            fx_source=self.fx_source,
            policy=self.policy,
            source_policy=self.source_policy,
        )
        self.writer = writer or MarketEvidenceWriter(session)
        self.health = health
        self.health_clock = health_clock
        self.health_token = health_token

    async def refresh(
        self,
        command: RefreshMarketEvidenceCommand,
    ) -> MarketEvidenceRefreshResult:
        if not isinstance(command, RefreshMarketEvidenceCommand):
            raise _fail()
        snapshot_timestamp = _timestamp(command.snapshot_timestamp)
        created_at = _timestamp(command.created_at)
        if self.session.in_transaction():
            raise _fail()
        async with self.session.begin():
            await self.read_boundary.set_transaction_repeatable_read_only()
            plan = _validate_plan(
                await self.planner.build(
                    BuildMarketEvidenceRefreshPlanCommand(
                        user_id=command.user_id,
                        snapshot_timestamp=snapshot_timestamp,
                    )
                ),
                user_id=command.user_id,
                snapshot_timestamp=snapshot_timestamp,
                price_registry=self.price_registry,
                fx_registry=self.fx_registry,
            )
        if self.session.in_transaction():
            raise _fail()

        if self.health is not None and plan.identity_failures:
            async with self.session.begin():
                for config_failure in plan.identity_failures:
                    observed_at = max(
                        _health_timestamp(self.health_clock()), config_failure.configured_at
                    )
                    recorded = await self.health.record(
                        listing_id=config_failure.listing_id,
                        provider=config_failure.provider,
                        provider_symbol=None,
                        outcome=ListingHealthOutcome(
                            attempt_started_at=config_failure.configured_at,
                            attempt_token="configuration:missing-provider-symbol",
                            observed_at=observed_at,
                            reason=config_failure.reason,
                        ),
                    )
                    if recorded is None:
                        raise _fail()

        claims: dict[int, _ClaimedPrice] = {}
        if self.health is not None and plan.price_requirements:
            try:
                # All claims commit together before any provider request. A denial
                # rolls back earlier claims so no unused lease survives this run.
                async with self.session.begin():
                    for index, requirement in sorted(
                        enumerate(plan.price_requirements),
                        key=lambda item: (
                            item[1].provider.value,
                            item[1].listing_id,
                            item[1].provider_symbol,
                        ),
                    ):
                        started_at = _health_timestamp(self.health_clock())
                        token = _nonblank(self.health_token())
                        if any(claim.token == token for claim in claims.values()):
                            raise _fail()
                        if not await self.health.claim(
                            listing_id=requirement.listing_id,
                            provider=requirement.provider,
                            provider_symbol=requirement.provider_symbol,
                            lease_owner=token,
                            now=started_at,
                            lease_for=_HEALTH_LEASE,
                        ):
                            raise _fail()
                        claims[index] = _ClaimedPrice(index, started_at, token)
            except Exception as exc:
                raise _fail() from exc
            if self.session.in_transaction():
                raise _fail()

        try:
            operations: list[Callable[[], Awaitable[_Acquisition]]] = []
            for price_index, price_requirement in enumerate(plan.price_requirements):

                async def _acquire_price(
                    *,
                    index: int = price_index,
                    requirement: PriceRequirement = price_requirement,
                ) -> _AcquiredPrice | _FailedPrice:
                    try:
                        price_provider = self.price_registry.get(requirement.provider)
                        observation = await price_provider.fetch(requirement)
                        return _AcquiredPrice(
                            index=index,
                            observation=validate_price_observation(
                                observation,
                                requirement=requirement,
                                policy=self.policy,
                            ),
                        )
                    except ProviderFailure as exc:
                        if self.health is None:
                            raise
                        return _FailedPrice(index, exc.reason, exc.retry_after)
                    except PriceObservationValidationError as exc:
                        if self.health is None:
                            raise
                        reason = getattr(exc, "reason", None)
                        if (
                            not isinstance(reason, MarketDataFailureReason)
                            or reason is MarketDataFailureReason.market_closed
                        ):
                            reason = MarketDataFailureReason.incomplete_response
                        return _FailedPrice(index, reason)
                    except Exception:
                        if self.health is None:
                            raise
                        return _FailedPrice(index, MarketDataFailureReason.incomplete_response)

                operations.append(_acquire_price)

            requirements_by_source: dict[
                ExchangeRateSource,
                list[tuple[int, ExchangeRateRequirement]],
            ] = {}
            for fx_index, fx_requirement in enumerate(plan.fx_requirements):
                requirements_by_source.setdefault(fx_requirement.provider, []).append(
                    (fx_index, fx_requirement)
                )
            for source, indexed_requirements in requirements_by_source.items():

                async def _acquire_fx_source(
                    *,
                    source: ExchangeRateSource = source,
                    indexed: tuple[tuple[int, ExchangeRateRequirement], ...] = tuple(
                        indexed_requirements
                    ),
                ) -> _AcquiredExchangeRates | _FailedFx:
                    try:
                        fx_provider = self.fx_registry.get(source)
                        ordered_requirements = tuple(requirement for _, requirement in indexed)
                        if isinstance(fx_provider, BatchExchangeRateProvider):
                            observations = await fx_provider.fetch_many(ordered_requirements)
                            if not isinstance(observations, tuple) or len(observations) != len(
                                ordered_requirements
                            ):
                                raise _fail()
                        else:
                            observations_list: list[ExchangeRateObservation] = []
                            for requirement in ordered_requirements:
                                observations_list.append(await fx_provider.fetch(requirement))
                            observations = tuple(observations_list)
                        return _AcquiredExchangeRates(
                            observations=tuple(
                                (
                                    index,
                                    validate_exchange_rate_observation(
                                        observation,
                                        requirement=requirement,
                                        policy=self.policy,
                                    ),
                                )
                                for (index, requirement), observation in zip(
                                    indexed,
                                    observations,
                                    strict=True,
                                )
                            )
                        )
                    except Exception:
                        if self.health is None:
                            raise
                        return _FailedFx()

                operations.append(_acquire_fx_source)

            acquired = await _acquire_bounded(tuple(operations))
            price_slots: list[PriceObservation | object] = [_UNSET] * len(plan.price_requirements)
            fx_slots: list[ExchangeRateObservation | object] = [_UNSET] * len(plan.fx_requirements)
            price_failures: dict[int, _FailedPrice] = {}
            fx_failed = False
            for acquisition in acquired:
                if isinstance(acquisition, _AcquiredPrice):
                    price_slots[acquisition.index] = acquisition.observation
                elif isinstance(acquisition, _FailedPrice):
                    price_failures[acquisition.index] = acquisition
                elif isinstance(acquisition, _FailedFx):
                    fx_failed = True
                else:
                    for index, observation in acquisition.observations:
                        fx_slots[index] = observation
            if self.health is not None:
                for index, requirement in enumerate(plan.price_requirements):
                    claim = claims[index]
                    failure = price_failures.get(index)
                    if failure is None:
                        continue
                    observed_at = max(_health_timestamp(self.health_clock()), claim.started_at)
                    retry_after = failure.retry_after if failure is not None else None
                    if retry_after is not None and (
                        retry_after.tzinfo is not None or retry_after <= observed_at
                    ):
                        retry_after = None
                    reason = failure.reason if failure is not None else None
                    next_session_at = None
                    if (
                        reason
                        in {
                            MarketDataFailureReason.incomplete_response,
                            MarketDataFailureReason.stale_timestamp,
                        }
                        and requirement.asset_type is not None
                    ):
                        calendar = assess_market(
                            requirement.listing_mic,
                            observed_at.replace(tzinfo=UTC),
                            asset_type=requirement.asset_type.value,
                        )
                        if (
                            calendar.status in {"closed", "weekend", "holiday"}
                            and calendar.next_session_at is not None
                        ):
                            reason = MarketDataFailureReason.market_closed
                            next_session_at = calendar.next_session_at.replace(tzinfo=None)
                    outcome = ListingHealthOutcome(
                        attempt_started_at=claim.started_at,
                        attempt_token=claim.token,
                        observed_at=observed_at,
                        reason=reason,
                        retry_after=retry_after,
                        next_session_at=next_session_at,
                    )
                    async with self.session.begin():
                        recorded = await self.health.record(
                            listing_id=requirement.listing_id,
                            provider=requirement.provider,
                            provider_symbol=requirement.provider_symbol,
                            outcome=outcome,
                            lease_owner=claim.token,
                        )
                        if recorded is None:
                            raise _fail()
            if price_failures or fx_failed:
                logger.warning(
                    "market_data_refresh_failed",
                    extra={
                        "price_failures": len(price_failures),
                        "fx_failed": fx_failed,
                        "fallback_count": sum(
                            requirement.fallback_reason is not None
                            for requirement in plan.price_requirements
                        ),
                    },
                )
                raise _fail()
            if any(observation is _UNSET for observation in price_slots) or any(
                observation is _UNSET for observation in fx_slots
            ):
                raise _fail()
            price_observations = [
                cast(PriceObservation, observation) for observation in price_slots
            ]
            exchange_rate_observations = [
                cast(ExchangeRateObservation, observation) for observation in fx_slots
            ]
            coalesced_prices = _coalesce_price_observations(tuple(price_observations))
            coalesced_rates = _coalesce_exchange_rate_observations(
                tuple(exchange_rate_observations)
            )
        except (
            PriceObservationValidationError,
            ExchangeRateObservationValidationError,
            MarketEvidenceStateError,
        ) as exc:
            raise _fail() from exc
        except Exception as exc:
            raise _fail() from exc

        async def finalize_health_success() -> None:
            if self.health is None:
                return
            for index, requirement in sorted(
                enumerate(plan.price_requirements),
                key=lambda item: (
                    item[1].provider.value,
                    item[1].listing_id,
                    item[1].provider_symbol,
                ),
            ):
                claim = claims[index]
                observed_at = max(_health_timestamp(self.health_clock()), claim.started_at)
                recorded = await self.health.record(
                    listing_id=requirement.listing_id,
                    provider=requirement.provider,
                    provider_symbol=requirement.provider_symbol,
                    outcome=ListingHealthOutcome(
                        attempt_started_at=claim.started_at,
                        attempt_token=claim.token,
                        observed_at=observed_at,
                    ),
                    lease_owner=claim.token,
                )
                if recorded is None:
                    raise _fail()

        persisted = await self.writer.write(
            PersistMarketEvidenceCommand(
                price_observations=coalesced_prices,
                exchange_rate_observations=coalesced_rates,
                created_at=created_at,
                reuse_persisted_fx_on_conflict=command.reuse_persisted_fx_on_conflict,
            ),
            transactional_finalize=(
                finalize_health_success
                if self.health is not None and plan.price_requirements
                else None
            ),
        )
        logger.info(
            "market_data_refresh_succeeded",
            extra={
                "price_count": len(plan.price_requirements),
                "fx_count": len(plan.fx_requirements),
                "fallback_count": sum(
                    requirement.fallback_reason is not None
                    for requirement in plan.price_requirements
                ),
            },
        )
        return MarketEvidenceRefreshResult(
            user_id=plan.user_id,
            snapshot_timestamp=plan.snapshot_timestamp,
            output_currency=plan.output_currency,
            required_price_count=len(plan.price_requirements),
            required_fx_count=len(plan.fx_requirements),
            price_ids=persisted.price_ids,
            exchange_rate_ids=persisted.exchange_rate_ids,
            prices_created=persisted.prices_created,
            prices_replayed=persisted.prices_replayed,
            rates_created=persisted.rates_created,
            rates_replayed=persisted.rates_replayed,
        )
