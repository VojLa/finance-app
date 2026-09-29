from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import cast

import pytest

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.acquisition_cache import CycleMarketAcquisitionCache
from app.modules.market_data.models import ExchangeRateRequirement, PriceRequirement
from app.modules.market_data.providers import (
    BatchExchangeRateProvider,
    ExchangeRateProviderRegistry,
    PriceProviderRegistry,
)
from app.modules.prices.models import PriceObservation

THROUGH = datetime(2026, 9, 3, 12, 5)


def _price_requirement(*, account_id: str = "account-a") -> PriceRequirement:
    return PriceRequirement(
        account_id=account_id,
        asset_id="asset-a",
        listing_id="listing-a",
        listing_currency="USD",
        provider=PriceSource.twelve_data,
        provider_symbol="AAPL",
        through=THROUGH,
    )


def _fx_requirement() -> ExchangeRateRequirement:
    return ExchangeRateRequirement(
        from_currency="USD",
        to_currency="EUR",
        provider=ExchangeRateSource.yahoo_finance,
        through=THROUGH,
    )


class _PriceProvider:
    source = PriceSource.twelve_data

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        self.calls += 1
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("temporary provider failure")
        return PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=requirement.provider,
            provider_symbol=requirement.provider_symbol,
            price=Decimal("1"),
            currency=requirement.listing_currency,
            observed_at=requirement.through,
        )


class _BatchFxProvider:
    source = ExchangeRateSource.yahoo_finance

    def __init__(self) -> None:
        self.single_calls = 0
        self.batch_calls = 0

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        self.single_calls += 1
        return self._observation(requirement)

    async def fetch_many(
        self, requirements: tuple[ExchangeRateRequirement, ...]
    ) -> tuple[ExchangeRateObservation, ...]:
        self.batch_calls += 1
        return tuple(self._observation(requirement) for requirement in requirements)

    @staticmethod
    def _observation(requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        return ExchangeRateObservation(
            from_currency=requirement.from_currency,
            to_currency=requirement.to_currency,
            provider=requirement.provider,
            rate=Decimal("0.9"),
            effective_at=requirement.through,
        )


def test_price_cache_coalesces_concurrent_users_and_resets_for_new_cycle() -> None:
    provider = _PriceProvider()
    registry = PriceProviderRegistry([provider])
    cache = CycleMarketAcquisitionCache()
    wrapped = cache.wrap_price_registry(registry).get(PriceSource.twelve_data)

    async def exercise() -> None:
        await asyncio.gather(
            wrapped.fetch(_price_requirement(account_id="account-a")),
            wrapped.fetch(_price_requirement(account_id="account-b")),
        )

    asyncio.run(exercise())
    assert provider.calls == 1

    new_cycle = CycleMarketAcquisitionCache()
    asyncio.run(
        new_cycle.wrap_price_registry(registry)
        .get(PriceSource.twelve_data)
        .fetch(_price_requirement())
    )
    assert provider.calls == 2


def test_failed_price_acquisition_is_not_cached() -> None:
    provider = _PriceProvider()
    wrapped = (
        CycleMarketAcquisitionCache()
        .wrap_price_registry(PriceProviderRegistry([provider]))
        .get(PriceSource.twelve_data)
    )
    provider.fail = True

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        asyncio.run(wrapped.fetch(_price_requirement()))
    provider.fail = False
    asyncio.run(wrapped.fetch(_price_requirement()))

    assert provider.calls == 2


def test_cached_batch_fx_provider_preserves_batch_acquisition() -> None:
    provider = _BatchFxProvider()
    wrapped = (
        CycleMarketAcquisitionCache()
        .wrap_fx_registry(ExchangeRateProviderRegistry([provider]))
        .get(ExchangeRateSource.yahoo_finance)
    )

    observations = asyncio.run(
        cast(BatchExchangeRateProvider, wrapped).fetch_many((_fx_requirement(), _fx_requirement()))
    )

    assert len(observations) == 2
    assert provider.batch_calls == 1
    assert provider.single_calls == 0
