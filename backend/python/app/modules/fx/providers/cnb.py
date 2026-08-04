"""CNB provider for exact foreign-currency to CZK observations."""

from __future__ import annotations

import re
from datetime import datetime, time
from decimal import Decimal, localcontext
from fractions import Fraction

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.providers.cnb_models import CnbFxHttpResponse
from app.modules.fx.providers.cnb_parser import parse_cnb_daily_rates
from app.modules.fx.providers.cnb_transport import CnbFxTransport
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
_MAX_RATE_SCALE = 8


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _exact_rate(czk_value: Decimal, amount: Decimal) -> Decimal:
    fraction = Fraction(czk_value) / Fraction(amount)
    denominator = fraction.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1 or max(twos, fives) > _MAX_RATE_SCALE:
        raise _fail()
    with localcontext() as context:
        context.prec = 64
        result = Decimal(fraction.numerator) / Decimal(fraction.denominator)
    if result * amount != czk_value:
        raise _fail()
    return result


class CnbExchangeRateProvider:
    source = ExchangeRateSource.cnb

    def __init__(
        self,
        transport: CnbFxTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch(
        self,
        requirement: ExchangeRateRequirement,
    ) -> ExchangeRateObservation:
        if (
            not isinstance(requirement, ExchangeRateRequirement)
            or requirement.provider is not self.source
            or not isinstance(requirement.from_currency, str)
            or not _CURRENCY_PATTERN.fullmatch(requirement.from_currency)
            or requirement.from_currency == "CZK"
            or not isinstance(requirement.to_currency, str)
            or requirement.to_currency != "CZK"
            or not isinstance(requirement.through, datetime)
            or requirement.through.tzinfo is not None
            or requirement.through.microsecond % 1_000 != 0
        ):
            raise _fail()
        response = await self._transport.fetch_daily_rates(requirement.through.date())
        if (
            not isinstance(response, CnbFxHttpResponse)
            or not isinstance(response.status_code, int)
            or response.status_code != 200
            or response.content_type not in {"application/xml", "text/xml"}
        ):
            raise _fail()
        document = parse_cnb_daily_rates(response.body)
        selected = next(
            (rate for rate in document.rates if rate.currency_code == requirement.from_currency),
            None,
        )
        if selected is None:
            raise _fail()
        observation = ExchangeRateObservation(
            from_currency=selected.currency_code,
            to_currency="CZK",
            provider=self.source,
            rate=_exact_rate(selected.czk_value, selected.amount),
            effective_at=datetime.combine(document.publication_date, time.min),
        )
        try:
            return validate_exchange_rate_observation(
                observation,
                requirement=requirement,
                policy=self._policy,
            )
        except ExchangeRateObservationValidationError as exc:
            raise _fail() from exc
