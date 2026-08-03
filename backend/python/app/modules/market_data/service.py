"""Orchestrate exact planning, provider I/O, validation, and atomic persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceRefreshResult,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.market_data.providers import (
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


@dataclass(frozen=True, slots=True)
class RefreshMarketEvidenceCommand:
    user_id: str
    snapshot_timestamp: datetime
    created_at: datetime


class _Planner(Protocol):
    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan: ...


class _Writer(Protocol):
    async def write(
        self,
        command: PersistMarketEvidenceCommand,
    ) -> PersistMarketEvidenceResult: ...


class _ReadBoundary(Protocol):
    async def set_transaction_repeatable_read_only(self) -> None: ...


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
    ):
        raise _fail()
    output_currency = _currency(value.output_currency)
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
        if (
            from_currency == to_currency
            or to_currency != output_currency
            or through > snapshot_timestamp
            or fx_key in fx_keys
        ):
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


class MarketEvidenceRefreshService:
    """Call providers only after an immutable read transaction has closed."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        price_registry: PriceProviderRegistry | None = None,
        fx_registry: ExchangeRateProviderRegistry | None = None,
        fx_source: ExchangeRateSource | None = None,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
        read_boundary: _ReadBoundary | None = None,
        planner: _Planner | None = None,
        writer: _Writer | None = None,
    ) -> None:
        self.session = session
        self.price_registry = price_registry or PriceProviderRegistry()
        self.fx_registry = fx_registry or ExchangeRateProviderRegistry()
        self.policy = validate_market_evidence_policy(policy)
        if fx_source is not None and fx_source not in self.fx_registry.sources:
            raise _fail()
        if fx_source is None and len(self.fx_registry.sources) == 1:
            fx_source = next(iter(self.fx_registry.sources))
        self.fx_source = fx_source
        self.read_boundary = read_boundary or MarketEvidenceRequirementsRepository(session)
        self.planner = planner or MarketEvidenceRequirementsPlanner(
            session,
            price_sources=self.price_registry.sources,
            fx_source=self.fx_source,
        )
        self.writer = writer or MarketEvidenceWriter(session)

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

        price_observations: list[PriceObservation] = []
        exchange_rate_observations: list[ExchangeRateObservation] = []
        try:
            for price_requirement in plan.price_requirements:
                price_provider = self.price_registry.get(price_requirement.provider)
                observation = await price_provider.fetch(price_requirement)
                price_observations.append(
                    validate_price_observation(
                        observation,
                        requirement=price_requirement,
                        policy=self.policy,
                    )
                )
            for fx_requirement in plan.fx_requirements:
                fx_provider = self.fx_registry.get(fx_requirement.provider)
                rate_observation = await fx_provider.fetch(fx_requirement)
                exchange_rate_observations.append(
                    validate_exchange_rate_observation(
                        rate_observation,
                        requirement=fx_requirement,
                        policy=self.policy,
                    )
                )
        except (
            PriceObservationValidationError,
            ExchangeRateObservationValidationError,
            MarketEvidenceStateError,
        ) as exc:
            raise _fail() from exc
        except Exception as exc:
            raise _fail() from exc

        persisted = await self.writer.write(
            PersistMarketEvidenceCommand(
                price_observations=tuple(price_observations),
                exchange_rate_observations=tuple(exchange_rate_observations),
                created_at=created_at,
            )
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
