"""Yahoo Finance provider for direct local-development FX evidence."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.models import ExchangeRateRequirement, MarketEvidenceStateError
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_parser import parse_yahoo_finance_chart
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
_MAX_CONCURRENT_PAIR_ACQUISITIONS = 4
_UNSET = object()


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _validate_requirement(requirement: object) -> ExchangeRateRequirement:
    if (
        not isinstance(requirement, ExchangeRateRequirement)
        or requirement.provider is not ExchangeRateSource.yahoo_finance
        or not _CURRENCY_PATTERN.fullmatch(requirement.from_currency)
        or not _CURRENCY_PATTERN.fullmatch(requirement.to_currency)
        or requirement.from_currency == requirement.to_currency
        or not isinstance(requirement.through, datetime)
        or requirement.through.tzinfo is not None
        or requirement.through.microsecond % 1_000 != 0
    ):
        raise _fail()
    return requirement


def _chart_symbol(from_currency: str, to_currency: str) -> str:
    """Return Yahoo's canonical direct ticker for one ordered FX pair.

    Yahoo represents USD-base pairs without the explicit ``USD`` prefix: for
    example, ``EUR=X`` is the direct USD-to-EUR quote. Other bases retain the
    explicit ordered pair, such as ``EURCZK=X``.
    """

    if from_currency == "USD":
        return f"{to_currency}=X"
    return f"{from_currency}{to_currency}=X"


class YahooFinanceExchangeRateProvider:
    source = ExchangeRateSource.yahoo_finance

    def __init__(
        self,
        transport: YahooFinanceChartTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        results = await self.fetch_many((requirement,))
        return results[0]

    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        if not isinstance(requirements, tuple) or not requirements:
            raise _fail()
        validated = tuple(_validate_requirement(requirement) for requirement in requirements)
        by_pair: dict[tuple[str, str], list[tuple[int, ExchangeRateRequirement]]] = defaultdict(
            list
        )
        for index, requirement in enumerate(validated):
            by_pair[(requirement.from_currency, requirement.to_currency)].append(
                (index, requirement)
            )
        observations: list[ExchangeRateObservation | None] = [None] * len(validated)

        async def _fetch_pair(
            pair_index: int,
            from_currency: str,
            to_currency: str,
            entries: list[tuple[int, ExchangeRateRequirement]],
        ) -> None:
            earliest = min(item.through for _, item in entries)
            latest = max(item.through for _, item in entries)
            symbol = _chart_symbol(from_currency, to_currency)
            async with semaphore:
                response = await self._transport.fetch_chart(
                    symbol,
                    start=earliest - self._policy.maximum_fx_age,
                    end=latest + timedelta(days=1),
                    interval="1d",
                )
                if (
                    not isinstance(response, YahooFinanceHttpResponse)
                    or response.status_code != 200
                    or response.content_type != "application/json"
                ):
                    raise _fail()
                chart = parse_yahoo_finance_chart(
                    response.body,
                    expected_symbol=symbol,
                    expected_currency=to_currency,
                    maximum_price_hint=8,
                )
                for index, requirement in entries:
                    point = next(
                        (item for item in chart.points if item.observed_at <= requirement.through),
                        None,
                    )
                    if point is None:
                        raise _fail()
                    observation = ExchangeRateObservation(
                        from_currency=from_currency,
                        to_currency=to_currency,
                        provider=self.source,
                        rate=point.close,
                        effective_at=point.observed_at,
                    )
                    try:
                        observations[index] = validate_exchange_rate_observation(
                            observation,
                            requirement=requirement,
                            policy=self._policy,
                        )
                    except ExchangeRateObservationValidationError as exc:
                        raise _fail() from exc
            completed_pairs[pair_index] = True

        ordered_pairs = tuple(sorted(by_pair.items()))
        completed_pairs: list[bool | object] = [_UNSET] * len(ordered_pairs)
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PAIR_ACQUISITIONS)
        try:
            async with asyncio.TaskGroup() as task_group:
                for pair_index, ((from_currency, to_currency), entries) in enumerate(ordered_pairs):
                    task_group.create_task(
                        _fetch_pair(pair_index, from_currency, to_currency, entries)
                    )
        except Exception as exc:
            raise _fail() from exc
        if any(completed is not True for completed in completed_pairs):
            raise _fail()
        if any(item is None for item in observations):
            raise _fail()
        return tuple(item for item in observations if item is not None)


__all__ = ["YahooFinanceExchangeRateProvider"]
