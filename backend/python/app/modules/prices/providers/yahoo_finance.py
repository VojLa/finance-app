"""Yahoo Finance adapter for exact alias-owned listed-security quotes.

This adapter is intentionally available only through the local-free source
policy.  It persists its own source identity and never impersonates Twelve
Data or a broker quote.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.yahoo_finance_identity import (
    YahooFinanceAssetIdentityError,
    parse_yahoo_finance_asset_identity,
)
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_parser import parse_yahoo_finance_chart
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


class YahooFinancePriceProvider:
    source = PriceSource.yahoo_finance

    def __init__(
        self,
        transport: YahooFinanceChartTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        if (
            not isinstance(requirement, PriceRequirement)
            or requirement.provider is not self.source
            or not isinstance(requirement.account_id, str)
            or not requirement.account_id
            or requirement.account_id != requirement.account_id.strip()
            or not isinstance(requirement.asset_id, str)
            or not requirement.asset_id
            or requirement.asset_id != requirement.asset_id.strip()
            or not isinstance(requirement.listing_id, str)
            or not requirement.listing_id
            or requirement.listing_id != requirement.listing_id.strip()
            or not isinstance(requirement.listing_currency, str)
            or not _CURRENCY_PATTERN.fullmatch(requirement.listing_currency)
            or not isinstance(requirement.through, datetime)
            or requirement.through.tzinfo is not None
            or requirement.through.microsecond % 1_000 != 0
        ):
            raise _fail()
        try:
            symbol = parse_yahoo_finance_asset_identity(requirement.provider_symbol)
        except YahooFinanceAssetIdentityError as exc:
            raise _fail() from exc
        response = await self._transport.fetch_chart(
            symbol,
            start=requirement.through - self._policy.maximum_price_age,
            end=requirement.through + timedelta(minutes=1),
            interval="1m",
        )
        if (
            not isinstance(response, YahooFinanceHttpResponse)
            or type(response.status_code) is not int
            or response.status_code != 200
            or response.content_type != "application/json"
        ):
            raise _fail()
        chart = parse_yahoo_finance_chart(
            response.body,
            expected_symbol=symbol,
            expected_currency=requirement.listing_currency,
            maximum_price_hint=10,
        )
        point = next(
            (item for item in chart.points if item.observed_at <= requirement.through), None
        )
        if point is None:
            raise _fail()
        observation = PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=self.source,
            provider_symbol=symbol,
            price=point.close,
            currency=requirement.listing_currency,
            observed_at=point.observed_at,
        )
        try:
            return validate_price_observation(
                observation,
                requirement=requirement,
                policy=self._policy,
            )
        except PriceObservationValidationError as exc:
            raise _fail() from exc


__all__ = ["YahooFinancePriceProvider"]
