from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.prices.providers.coingecko import CoinGeckoPriceProvider
from app.modules.prices.providers.coingecko_models import CoinGeckoHttpResponse

OBSERVED_AT = datetime(2026, 8, 4, 8, 19)
OBSERVED_EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())


class FakeTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def fetch_simple_price(
        self,
        provider_symbol: str,
        quote_currency: str,
    ) -> CoinGeckoHttpResponse:
        self.calls.append((provider_symbol, quote_currency))
        return CoinGeckoHttpResponse(200, "application/json", self.body)


def _body(
    symbol: str = "bitcoin",
    currency: str = "eur",
    price: str = "61234.123456789",
    timestamp: int = OBSERVED_EPOCH,
) -> bytes:
    return (f'{{"{symbol}":{{"{currency}":{price},"last_updated_at":{timestamp}}}}}').encode()


def _requirement(
    *,
    provider: PriceSource = PriceSource.coingecko,
    symbol: str = "bitcoin",
    currency: str = "EUR",
    through: datetime = OBSERVED_AT + timedelta(hours=1),
) -> PriceRequirement:
    return PriceRequirement(
        account_id="account-1",
        asset_id="asset-1",
        listing_id="listing-1",
        listing_currency=currency,
        provider=provider,
        provider_symbol=symbol,
        through=through,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("symbol", "currency"),
    [("bitcoin", "EUR"), ("ethereum", "CZK")],
)
async def test_provider_returns_exact_canonical_observation(
    symbol: str,
    currency: str,
) -> None:
    transport = FakeTransport(_body(symbol, currency.lower()))

    result = await CoinGeckoPriceProvider(transport).fetch(
        _requirement(symbol=symbol, currency=currency)
    )

    assert transport.calls == [(symbol, currency.lower())]
    assert result.asset_id == "asset-1"
    assert result.listing_id == "listing-1"
    assert result.provider is PriceSource.coingecko
    assert result.provider_symbol == symbol
    assert result.currency == currency
    assert result.price == Decimal("61234.123456789")
    assert result.observed_at == OBSERVED_AT


@pytest.mark.asyncio
async def test_provider_accepts_exact_72_hour_boundary() -> None:
    transport = FakeTransport(_body())
    result = await CoinGeckoPriceProvider(transport).fetch(
        _requirement(through=OBSERVED_AT + timedelta(hours=72))
    )
    assert result.observed_at == OBSERVED_AT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "through",
    [
        OBSERVED_AT - timedelta(milliseconds=1),
        OBSERVED_AT + timedelta(hours=72, milliseconds=1),
    ],
)
async def test_provider_rejects_future_or_stale_evidence(through: datetime) -> None:
    transport = FakeTransport(_body())
    with pytest.raises(MarketEvidenceStateError):
        await CoinGeckoPriceProvider(transport).fetch(_requirement(through=through))
    assert transport.calls == [("bitcoin", "eur")]


@pytest.mark.asyncio
async def test_provider_rejects_nonrepresentable_price() -> None:
    transport = FakeTransport(_body(price="1.12345678901"))
    with pytest.raises(MarketEvidenceStateError):
        await CoinGeckoPriceProvider(transport).fetch(_requirement())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requirement",
    [
        _requirement(provider=PriceSource.exchange),
        _requirement(symbol=""),
        _requirement(symbol=" bitcoin"),
        _requirement(symbol="bit,coin"),
        _requirement(symbol="bit&coin"),
        _requirement(symbol="bit/coin"),
        _requirement(symbol="bitčoin"),
        _requirement(symbol="x" * 129),
        _requirement(currency="eur"),
        _requirement(currency="EU"),
        _requirement(through=datetime(2026, 8, 4, 9, 0, 0, 1)),
    ],
)
async def test_provider_rejects_invalid_requirement_before_http(
    requirement: PriceRequirement,
) -> None:
    transport = FakeTransport(_body())
    with pytest.raises(MarketEvidenceStateError):
        await CoinGeckoPriceProvider(transport).fetch(requirement)
    assert transport.calls == []


def test_provider_has_no_clock_or_database_boundary() -> None:
    source = inspect.getsource(CoinGeckoPriceProvider)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "sqlalchemy" not in source
    assert "session" not in source
