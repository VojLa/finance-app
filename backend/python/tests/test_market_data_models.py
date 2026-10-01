from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AssetType,
    ExchangeRateSource,
    MarketDataFailureReason,
    PriceSource,
)
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.models import ExchangeRateRequirement, PriceRequirement
from app.modules.market_data.policy import MarketEvidencePolicy
from app.modules.prices.models import PriceObservation
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

THROUGH = datetime(2026, 8, 3, 12, 0, 0, 123000)
POLICY = MarketEvidencePolicy(timedelta(hours=72), timedelta(days=7))
PRICE_REQUIREMENT = PriceRequirement(
    account_id="account-1",
    asset_id="asset-1",
    listing_id="listing-1",
    listing_currency="EUR",
    provider=PriceSource.yahoo_finance,
    provider_symbol="EXACT",
    through=THROUGH,
)
FX_REQUIREMENT = ExchangeRateRequirement(
    from_currency="EUR",
    to_currency="CZK",
    through=THROUGH,
    provider=ExchangeRateSource.ecb,
)


def _price(**changes: object) -> PriceObservation:
    values = PriceObservation(
        asset_id="asset-1",
        listing_id="listing-1",
        provider=PriceSource.yahoo_finance,
        provider_symbol="EXACT",
        price=Decimal("123.1234567890"),
        currency="EUR",
        observed_at=THROUGH - timedelta(hours=1),
    )
    return replace(values, **cast(Any, changes))


def _rate(**changes: object) -> ExchangeRateObservation:
    values = ExchangeRateObservation(
        from_currency="EUR",
        to_currency="CZK",
        provider=ExchangeRateSource.ecb,
        rate=Decimal("25.12345678"),
        effective_at=THROUGH - timedelta(days=1),
    )
    return replace(values, **cast(Any, changes))


def test_price_observation_is_immutable_and_preserved_exactly() -> None:
    observation = _price()
    assert (
        validate_price_observation(
            observation,
            requirement=PRICE_REQUIREMENT,
            policy=POLICY,
        )
        == observation
    )
    with pytest.raises(FrozenInstanceError):
        observation.price = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    "observation",
    [
        object(),
        _price(asset_id="asset-2"),
        _price(listing_id="listing-2"),
        _price(provider=PriceSource.stooq),
        _price(provider_symbol="OTHER"),
        _price(provider_symbol=" EXACT"),
        _price(currency="USD"),
        _price(currency="eur"),
        _price(price=Decimal("0")),
        _price(price=Decimal("-1")),
        _price(price=Decimal("NaN")),
        _price(price=Decimal("Infinity")),
        _price(price=Decimal("1.00000000001")),
        _price(price=Decimal("1234567890123456789")),
        _price(observed_at=THROUGH + timedelta(milliseconds=1)),
        _price(observed_at=THROUGH - timedelta(hours=72, milliseconds=1)),
        _price(observed_at=datetime(2026, 8, 3, tzinfo=UTC)),
        _price(observed_at=datetime(2026, 8, 3, microsecond=1)),
    ],
)
def test_price_observation_fails_closed(observation: object) -> None:
    with pytest.raises(PriceObservationValidationError):
        validate_price_observation(
            observation,
            requirement=PRICE_REQUIREMENT,
            policy=POLICY,
        )


def test_price_exact_freshness_boundary_is_accepted() -> None:
    observation = _price(observed_at=THROUGH - timedelta(hours=72))
    assert (
        validate_price_observation(
            observation,
            requirement=PRICE_REQUIREMENT,
            policy=POLICY,
        ).observed_at
        == observation.observed_at
    )


@pytest.mark.parametrize(
    ("observation", "reason"),
    [
        (_price(provider_symbol="OTHER"), MarketDataFailureReason.provider_identity_conflict),
        (_price(currency="USD"), MarketDataFailureReason.currency_conflict),
        (_price(price=Decimal("0")), MarketDataFailureReason.invalid_price),
        (
            _price(observed_at=THROUGH - timedelta(hours=73)),
            MarketDataFailureReason.stale_timestamp,
        ),
    ],
)
def test_price_validation_exposes_only_safe_health_reason(
    observation: PriceObservation,
    reason: MarketDataFailureReason,
) -> None:
    with pytest.raises(PriceObservationValidationError) as caught:
        validate_price_observation(
            observation,
            requirement=PRICE_REQUIREMENT,
            policy=POLICY,
        )
    assert caught.value.reason is reason


def test_expected_previous_close_after_long_holiday_is_not_stale() -> None:
    through = datetime(2026, 9, 8, 13)
    requirement = replace(
        PRICE_REQUIREMENT,
        through=through,
        listing_mic="XNAS",
        asset_type=AssetType.etf,
    )
    observation = _price(observed_at=datetime(2026, 9, 4, 20))

    assert (
        validate_price_observation(
            observation,
            requirement=requirement,
            policy=POLICY,
        ).observed_at
        == observation.observed_at
    )


def test_old_previous_close_during_open_session_is_stale() -> None:
    requirement = replace(
        PRICE_REQUIREMENT,
        through=datetime(2026, 9, 8, 15),
        listing_mic="XNAS",
        asset_type=AssetType.etf,
    )
    with pytest.raises(PriceObservationValidationError):
        validate_price_observation(
            _price(observed_at=datetime(2026, 9, 4, 20)),
            requirement=requirement,
            policy=POLICY,
        )


def test_crypto_does_not_receive_exchange_calendar_freshness_exception() -> None:
    requirement = replace(
        PRICE_REQUIREMENT,
        through=datetime(2026, 9, 8, 13),
        listing_mic=None,
        asset_type=AssetType.crypto,
    )
    with pytest.raises(PriceObservationValidationError):
        validate_price_observation(
            _price(observed_at=datetime(2026, 9, 4, 20)),
            requirement=requirement,
            policy=POLICY,
        )


def test_exchange_rate_observation_is_immutable_and_preserved_exactly() -> None:
    observation = _rate()
    assert (
        validate_exchange_rate_observation(
            observation,
            requirement=FX_REQUIREMENT,
            policy=POLICY,
        )
        == observation
    )
    with pytest.raises(FrozenInstanceError):
        observation.rate = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    "observation",
    [
        object(),
        _rate(from_currency="USD"),
        _rate(to_currency="EUR"),
        _rate(to_currency="EUR", from_currency="EUR"),
        _rate(provider=ExchangeRateSource.twelve_data),
        _rate(from_currency="eur"),
        _rate(to_currency="CZ"),
        _rate(rate=Decimal("0")),
        _rate(rate=Decimal("-1")),
        _rate(rate=Decimal("NaN")),
        _rate(rate=Decimal("Infinity")),
        _rate(rate=Decimal("1.000000001")),
        _rate(rate=Decimal("12345678901")),
        _rate(effective_at=THROUGH + timedelta(milliseconds=1)),
        _rate(effective_at=THROUGH - timedelta(days=7, milliseconds=1)),
        _rate(effective_at=datetime(2026, 8, 3, tzinfo=UTC)),
        _rate(effective_at=datetime(2026, 8, 3, microsecond=1)),
    ],
)
def test_exchange_rate_observation_fails_closed(observation: object) -> None:
    with pytest.raises(ExchangeRateObservationValidationError):
        validate_exchange_rate_observation(
            observation,
            requirement=FX_REQUIREMENT,
            policy=POLICY,
        )


def test_exchange_rate_exact_freshness_boundary_is_accepted() -> None:
    observation = _rate(effective_at=THROUGH - timedelta(days=7))
    assert (
        validate_exchange_rate_observation(
            observation,
            requirement=FX_REQUIREMENT,
            policy=POLICY,
        ).effective_at
        == observation.effective_at
    )
