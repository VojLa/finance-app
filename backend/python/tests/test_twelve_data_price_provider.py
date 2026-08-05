from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.prices.providers.twelve_data import TwelveDataPriceProvider
from app.modules.prices.providers.twelve_data_identity import TwelveDataQuoteIdentity
from app.modules.prices.providers.twelve_data_models import TwelveDataHttpResponse

OBSERVED_AT = datetime(2026, 8, 5, 12, 34)
EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())
ALIAS = '{"symbol":"AAPL","mic_code":"XNAS"}'


def _body(
    *,
    close: str = "225.3200000000",
    timestamp: int = EPOCH,
    symbol: str = "AAPL",
    mic_code: str = "XNAS",
    currency: str = "USD",
) -> bytes:
    observed = datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f'{{"symbol":"{symbol}","mic_code":"{mic_code}","currency":"{currency}",'
        f'"datetime":"{observed}","timestamp":{timestamp},"last_quote_at":{timestamp},'
        f'"close":"{close}"}}'
    ).encode()


class FakeTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[TwelveDataQuoteIdentity] = []

    async def fetch_quote(
        self,
        identity: TwelveDataQuoteIdentity,
    ) -> TwelveDataHttpResponse:
        self.calls.append(identity)
        return TwelveDataHttpResponse(200, "application/json", self.body)


def _requirement(
    *,
    provider: PriceSource = PriceSource.twelve_data,
    alias: str = ALIAS,
    currency: str = "USD",
    through: datetime = OBSERVED_AT + timedelta(hours=1),
) -> PriceRequirement:
    return PriceRequirement(
        account_id="account-1",
        asset_id="asset-1",
        listing_id="listing-1",
        listing_currency=currency,
        provider=provider,
        provider_symbol=alias,
        through=through,
    )


@pytest.mark.asyncio
async def test_provider_returns_exact_canonical_observation() -> None:
    transport = FakeTransport(_body())
    result = await TwelveDataPriceProvider(transport).fetch(_requirement())
    assert transport.calls == [TwelveDataQuoteIdentity("AAPL", "XNAS")]
    assert result.asset_id == "asset-1"
    assert result.listing_id == "listing-1"
    assert result.provider is PriceSource.twelve_data
    assert result.provider_symbol == ALIAS
    assert result.currency == "USD"
    assert result.price == Decimal("225.3200000000")
    assert result.observed_at == OBSERVED_AT


@pytest.mark.asyncio
async def test_provider_accepts_exact_72_hour_boundary() -> None:
    transport = FakeTransport(_body())
    result = await TwelveDataPriceProvider(transport).fetch(
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
async def test_provider_rejects_future_or_stale_quote(through: datetime) -> None:
    transport = FakeTransport(_body())
    with pytest.raises(MarketEvidenceStateError):
        await TwelveDataPriceProvider(transport).fetch(_requirement(through=through))
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requirement",
    [
        _requirement(provider=PriceSource.broker),
        _requirement(alias=""),
        _requirement(alias='{"symbol":"AAPL","mic_code":"xnas"}'),
        _requirement(alias='{"symbol":"AAPL,MSFT","mic_code":"XNAS"}'),
        _requirement(currency="usd"),
        _requirement(currency="US"),
        _requirement(through=datetime(2026, 8, 5, 13, 0, 0, 1)),
    ],
)
async def test_provider_rejects_invalid_requirement_before_http(
    requirement: PriceRequirement,
) -> None:
    transport = FakeTransport(_body())
    with pytest.raises(MarketEvidenceStateError):
        await TwelveDataPriceProvider(transport).fetch(requirement)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        _body(symbol="MSFT"),
        _body(mic_code="XNYS"),
        _body(currency="EUR"),
        _body(close="0"),
        _body(close="1.12345678901"),
    ],
)
async def test_provider_rejects_incompatible_response(body: bytes) -> None:
    transport = FakeTransport(body)
    with pytest.raises(MarketEvidenceStateError):
        await TwelveDataPriceProvider(transport).fetch(_requirement())
    assert len(transport.calls) == 1


def test_provider_has_no_clock_database_or_identity_inference() -> None:
    source = inspect.getsource(TwelveDataPriceProvider)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "sqlalchemy" not in source
    assert "session" not in source
    assert ".isin" not in source.lower()
    assert "listing.mic" not in source
