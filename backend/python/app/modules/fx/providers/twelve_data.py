"""Twelve Data provider for exact direct-pair FX observations."""

from __future__ import annotations

import re
from datetime import datetime

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.providers.twelve_data_models import TwelveDataFxHttpResponse
from app.modules.fx.providers.twelve_data_parser import (
    TwelveDataFxParseError,
    parse_twelve_data_fx,
)
from app.modules.fx.providers.twelve_data_transport import TwelveDataFxTransport
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

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


class TwelveDataExchangeRateProvider:
    source = ExchangeRateSource.twelve_data

    def __init__(
        self,
        transport: TwelveDataFxTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        if (
            not isinstance(requirement, ExchangeRateRequirement)
            or requirement.provider is not self.source
            or not _CURRENCY_PATTERN.fullmatch(requirement.from_currency)
            or not _CURRENCY_PATTERN.fullmatch(requirement.to_currency)
            or requirement.from_currency == requirement.to_currency
            or not isinstance(requirement.through, datetime)
            or requirement.through.tzinfo is not None
            or requirement.through.microsecond % 1_000 != 0
        ):
            raise _fail()
        symbol = f"{requirement.from_currency}/{requirement.to_currency}"
        response = await self._transport.fetch(
            requirement.from_currency, requirement.to_currency, requirement.through.date()
        )
        if (
            not isinstance(response, TwelveDataFxHttpResponse)
            or response.status_code != 200
            or response.content_type != "application/json"
        ):
            raise _fail()
        try:
            points = parse_twelve_data_fx(response.body, expected_symbol=symbol)
        except TwelveDataFxParseError as exc:
            raise _fail() from exc
        selected = next(
            (point for point in points if point.effective_at <= requirement.through), None
        )
        if selected is None:
            raise _fail()
        observation = ExchangeRateObservation(
            from_currency=requirement.from_currency,
            to_currency=requirement.to_currency,
            provider=self.source,
            rate=selected.rate,
            effective_at=selected.effective_at,
        )
        try:
            return validate_exchange_rate_observation(
                observation, requirement=requirement, policy=self._policy
            )
        except ExchangeRateObservationValidationError as exc:
            raise _fail() from exc
