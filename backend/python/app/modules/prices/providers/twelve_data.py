"""Twelve Data adapter for exact alias-owned listed-security quotes."""

from __future__ import annotations

import re
from datetime import datetime

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.twelve_data_identity import (
    parse_twelve_data_quote_identity,
)
from app.modules.prices.providers.twelve_data_models import TwelveDataHttpResponse
from app.modules.prices.providers.twelve_data_parser import parse_twelve_data_quote
from app.modules.prices.providers.twelve_data_transport import TwelveDataPriceTransport
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


class TwelveDataPriceProvider:
    source = PriceSource.twelve_data

    def __init__(
        self,
        transport: TwelveDataPriceTransport,
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
        identity = parse_twelve_data_quote_identity(requirement.provider_symbol)
        response = await self._transport.fetch_quote(identity)
        if (
            not isinstance(response, TwelveDataHttpResponse)
            or type(response.status_code) is not int
            or response.status_code != 200
            or response.content_type != "application/json"
        ):
            raise _fail()
        parsed = parse_twelve_data_quote(
            response.body,
            identity=identity,
            listing_currency=requirement.listing_currency,
        )
        observation = PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=self.source,
            provider_symbol=requirement.provider_symbol,
            price=parsed.close,
            currency=requirement.listing_currency,
            observed_at=parsed.last_quote_at_utc,
        )
        try:
            return validate_price_observation(
                observation,
                requirement=requirement,
                policy=self._policy,
            )
        except PriceObservationValidationError as exc:
            raise _fail() from exc
