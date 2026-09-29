"""I/O ports for historical ranges; current quote ports remain separate."""

from __future__ import annotations

from typing import Protocol

from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.history.models import (
    HistoricalExchangeRateProviderCapability,
    HistoricalExchangeRateRangeRequirement,
    HistoricalPriceProviderCapability,
    HistoricalPriceRangeRequirement,
)
from app.modules.prices.models import PriceObservation


class HistoricalPriceProvider(Protocol):
    capability: HistoricalPriceProviderCapability

    async def fetch_range(
        self,
        requirement: HistoricalPriceRangeRequirement,
    ) -> tuple[PriceObservation, ...]: ...


class HistoricalExchangeRateProvider(Protocol):
    capability: HistoricalExchangeRateProviderCapability

    async def fetch_range(
        self,
        requirement: HistoricalExchangeRateRangeRequirement,
    ) -> tuple[ExchangeRateObservation, ...]: ...


__all__ = ["HistoricalExchangeRateProvider", "HistoricalPriceProvider"]
