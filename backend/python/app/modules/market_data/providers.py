"""Provider I/O ports and exact source registries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.prices.models import PriceObservation


class PriceProvider(Protocol):
    source: PriceSource

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation: ...


class ExchangeRateProvider(Protocol):
    source: ExchangeRateSource

    async def fetch(
        self,
        requirement: ExchangeRateRequirement,
    ) -> ExchangeRateObservation: ...


class PriceProviderRegistry:
    def __init__(self, providers: Iterable[PriceProvider] = ()) -> None:
        registered: dict[PriceSource, PriceProvider] = {}
        for provider in providers:
            source = getattr(provider, "source", None)
            if (
                not isinstance(source, PriceSource)
                or source is PriceSource.manual
                or source in registered
            ):
                raise MarketEvidenceStateError()
            registered[source] = provider
        self._providers = registered

    @property
    def sources(self) -> frozenset[PriceSource]:
        return frozenset(self._providers)

    def get(self, source: PriceSource) -> PriceProvider:
        provider = self._providers.get(source)
        if provider is None:
            raise MarketEvidenceStateError()
        return provider


class ExchangeRateProviderRegistry:
    def __init__(self, providers: Iterable[ExchangeRateProvider] = ()) -> None:
        registered: dict[ExchangeRateSource, ExchangeRateProvider] = {}
        for provider in providers:
            source = getattr(provider, "source", None)
            if (
                not isinstance(source, ExchangeRateSource)
                or source is ExchangeRateSource.manual
                or source in registered
            ):
                raise MarketEvidenceStateError()
            registered[source] = provider
        self._providers = registered

    @property
    def sources(self) -> frozenset[ExchangeRateSource]:
        return frozenset(self._providers)

    def get(self, source: ExchangeRateSource) -> ExchangeRateProvider:
        provider = self._providers.get(source)
        if provider is None:
            raise MarketEvidenceStateError()
        return provider
