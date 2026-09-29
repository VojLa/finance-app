"""Cycle-scoped, in-process deduplication for public market-provider acquisitions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Hashable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import validate_exchange_rate_observation
from app.modules.market_data.models import ExchangeRateRequirement, PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.market_data.providers import (
    BatchExchangeRateProvider,
    ExchangeRateProvider,
    ExchangeRateProviderRegistry,
    PriceProvider,
    PriceProviderRegistry,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.validation import validate_price_observation

T = TypeVar("T")
K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True, slots=True)
class _PriceKey:
    asset_id: str
    listing_id: str
    listing_currency: str
    provider: PriceSource
    provider_symbol: str
    through: datetime


@dataclass(frozen=True, slots=True)
class _FxKey:
    from_currency: str
    to_currency: str
    provider: ExchangeRateSource
    through: datetime


class CycleMarketAcquisitionCache:
    """Share only successful provider observations for one scheduled refresh cycle."""

    def __init__(self, *, policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY) -> None:
        self._price_tasks: dict[_PriceKey, asyncio.Task[PriceObservation]] = {}
        self._fx_tasks: dict[_FxKey, asyncio.Task[ExchangeRateObservation]] = {}
        self._lock = asyncio.Lock()
        self._policy = validate_market_evidence_policy(policy)

    async def _acquire(
        self,
        tasks: dict[K, asyncio.Task[T]],
        key: K,
        acquire: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        async with self._lock:
            task = tasks.get(key)
            if task is None:
                task = asyncio.create_task(acquire())
                tasks[key] = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                if tasks.get(key) is task:
                    tasks.pop(key, None)
            raise

    async def acquire_price(
        self,
        provider: PriceProvider,
        requirement: PriceRequirement,
    ) -> PriceObservation:
        key = _PriceKey(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            listing_currency=requirement.listing_currency,
            provider=requirement.provider,
            provider_symbol=requirement.provider_symbol,
            through=requirement.through,
        )

        async def fetch_validated() -> PriceObservation:
            return validate_price_observation(
                await provider.fetch(requirement), requirement=requirement, policy=self._policy
            )

        return await self._acquire(self._price_tasks, key, fetch_validated)

    async def acquire_fx(
        self,
        provider: ExchangeRateProvider,
        requirement: ExchangeRateRequirement,
    ) -> ExchangeRateObservation:
        key = _FxKey(
            from_currency=requirement.from_currency,
            to_currency=requirement.to_currency,
            provider=requirement.provider,
            through=requirement.through,
        )

        async def fetch_validated() -> ExchangeRateObservation:
            return validate_exchange_rate_observation(
                await provider.fetch(requirement), requirement=requirement, policy=self._policy
            )

        return await self._acquire(self._fx_tasks, key, fetch_validated)

    async def acquire_fx_many(
        self,
        provider: ExchangeRateProvider,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        if not requirements:
            return ()
        if not isinstance(provider, BatchExchangeRateProvider):
            return tuple(
                await asyncio.gather(
                    *(self.acquire_fx(provider, requirement) for requirement in requirements)
                )
            )

        keys = tuple(
            _FxKey(
                from_currency=requirement.from_currency,
                to_currency=requirement.to_currency,
                provider=requirement.provider,
                through=requirement.through,
            )
            for requirement in requirements
        )
        async with self._lock:
            pending: list[tuple[_FxKey, ExchangeRateRequirement]] = []
            pending_keys: set[_FxKey] = set()
            for key, requirement in zip(keys, requirements, strict=True):
                if key not in self._fx_tasks and key not in pending_keys:
                    pending.append((key, requirement))
                    pending_keys.add(key)
            if pending:
                batch = asyncio.create_task(
                    self._fetch_validated_batch(provider, tuple(item[1] for item in pending))
                )
                for index, (key, _) in enumerate(pending):
                    self._fx_tasks[key] = asyncio.create_task(self._batch_item(batch, index))
            tasks = tuple(self._fx_tasks[key] for key in keys)
        try:
            return tuple(await asyncio.gather(*(asyncio.shield(task) for task in tasks)))
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                for key, task in zip(keys, tasks, strict=True):
                    if self._fx_tasks.get(key) is task:
                        self._fx_tasks.pop(key, None)
            raise

    @staticmethod
    async def _batch_item(
        batch: asyncio.Task[tuple[ExchangeRateObservation, ...]],
        index: int,
    ) -> ExchangeRateObservation:
        return (await batch)[index]

    async def _fetch_validated_batch(
        self,
        provider: BatchExchangeRateProvider,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        observations = await provider.fetch_many(requirements)
        if not isinstance(observations, tuple) or len(observations) != len(requirements):
            raise ValueError("Batch exchange-rate provider returned incompatible evidence.")
        return tuple(
            validate_exchange_rate_observation(
                observation,
                requirement=requirement,
                policy=self._policy,
            )
            for observation, requirement in zip(observations, requirements, strict=True)
        )

    def wrap_price_registry(self, registry: PriceProviderRegistry) -> PriceProviderRegistry:
        return PriceProviderRegistry(
            _CachedPriceProvider(provider, self)
            for source in registry.sources
            for provider in (registry.get(source),)
        )

    def wrap_fx_registry(
        self, registry: ExchangeRateProviderRegistry
    ) -> ExchangeRateProviderRegistry:
        return ExchangeRateProviderRegistry(
            _CachedExchangeRateProvider(provider, self)
            for source in registry.sources
            for provider in (registry.get(source),)
        )


class _CachedPriceProvider:
    def __init__(self, provider: PriceProvider, cache: CycleMarketAcquisitionCache) -> None:
        self.source = provider.source
        self._provider = provider
        self._cache = cache

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        return await self._cache.acquire_price(self._provider, requirement)


class _CachedExchangeRateProvider:
    def __init__(self, provider: ExchangeRateProvider, cache: CycleMarketAcquisitionCache) -> None:
        self.source = provider.source
        self._provider = provider
        self._cache = cache

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        return await self._cache.acquire_fx(self._provider, requirement)

    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        return await self._cache.acquire_fx_many(self._provider, requirements)


__all__ = ["CycleMarketAcquisitionCache"]
