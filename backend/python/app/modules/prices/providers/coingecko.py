"""CoinGecko adapter for exact alias-owned crypto price requirements."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.coingecko_identity import (
    CoinGeckoAssetIdentityError,
    parse_coingecko_asset_identity,
)
from app.modules.prices.providers.coingecko_models import CoinGeckoHttpResponse
from app.modules.prices.providers.coingecko_parser import parse_coingecko_simple_price
from app.modules.prices.providers.coingecko_transport import CoinGeckoPriceTransport
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _valid_provider_symbol(value: object) -> bool:
    try:
        parse_coingecko_asset_identity(value)
    except CoinGeckoAssetIdentityError:
        return False
    return True


class CoinGeckoPriceProvider:
    source = PriceSource.coingecko

    def __init__(
        self,
        transport: CoinGeckoPriceTransport,
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
            or not _valid_provider_symbol(requirement.provider_symbol)
            or not isinstance(requirement.through, datetime)
            or requirement.through.tzinfo is not None
            or requirement.through.microsecond % 1_000 != 0
        ):
            raise _fail()
        quote_currency = requirement.listing_currency.lower()
        response = await self._transport.fetch_simple_price(
            requirement.provider_symbol,
            quote_currency,
        )
        if (
            not isinstance(response, CoinGeckoHttpResponse)
            or type(response.status_code) is not int
            or response.status_code != 200
            or response.content_type != "application/json"
        ):
            raise _fail()
        parsed = parse_coingecko_simple_price(
            response.body,
            provider_symbol=requirement.provider_symbol,
            quote_currency=quote_currency,
        )
        try:
            observed_at = datetime.fromtimestamp(parsed.last_updated_at, tz=UTC).replace(
                tzinfo=None
            )
        except (OverflowError, OSError, ValueError) as exc:
            raise _fail() from exc
        observation = PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=self.source,
            provider_symbol=requirement.provider_symbol,
            price=parsed.price,
            currency=requirement.listing_currency,
            observed_at=observed_at,
        )
        try:
            return validate_price_observation(
                observation,
                requirement=requirement,
                policy=self._policy,
            )
        except PriceObservationValidationError as exc:
            raise _fail() from exc
