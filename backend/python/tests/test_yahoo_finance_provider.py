from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import PriceSource
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.prices.providers.yahoo_finance import YahooFinancePriceProvider
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport

OBSERVED_AT = datetime(2026, 8, 5, 12)


def _body(
    *,
    close: str = "128.039993286133",
    price_hint: int = 2,
    symbol: str = "VUAA.MI",
    currency: str = "EUR",
    observed_at: datetime = OBSERVED_AT,
    granularity: str | None = "1m",
) -> bytes:
    epoch = int(observed_at.replace(tzinfo=UTC).timestamp())
    document = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "currency": currency,
                        "priceHint": price_hint,
                        "dataGranularity": granularity,
                        "exchangeName": "Milan",
                    },
                    "timestamp": [epoch],
                    "indicators": {
                        "quote": [{"close": ["__CLOSE__"]}],
                        "adjclose": [{"adjclose": ["__CLOSE__"]}],
                    },
                }
            ],
            "error": None,
        }
    }
    return json.dumps(document, separators=(",", ":")).replace('"__CLOSE__"', close).encode()


class _Transport(YahooFinanceChartTransport):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[str, datetime, datetime, str]] = []

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        self.calls.append((symbol, start, end, interval))
        return YahooFinanceHttpResponse(200, "application/json", self.body)


def _requirement(*, symbol: str = "VUAA.MI", currency: str = "EUR") -> PriceRequirement:
    return PriceRequirement(
        account_id="account-1",
        asset_id="asset-1",
        listing_id="listing-1",
        listing_currency=currency,
        provider=PriceSource.yahoo_finance,
        provider_symbol=symbol,
        through=OBSERVED_AT + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_provider_records_yahoo_price_with_price_hint_normalization() -> None:
    transport = _Transport(_body())

    result = await YahooFinancePriceProvider(transport).fetch(_requirement())

    assert result.provider is PriceSource.yahoo_finance
    assert result.provider_symbol == "VUAA.MI"
    assert result.currency == "EUR"
    assert result.price == Decimal("128.04")
    assert transport.calls[0][0] == "VUAA.MI"
    assert transport.calls[0][3] == "1m"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "symbol,currency",
    [
        ("AAPL", "USD"),
        ("VWCE.DE", "EUR"),
        ("CEZ.PR", "CZK"),
        ("VUSA.L", "GBP"),
        ("NESN.SW", "CHF"),
        ("BTC-USD", "USD"),
    ],
)
async def test_provider_preserves_exact_symbol_and_native_currency(
    symbol: str, currency: str
) -> None:
    transport = _Transport(_body(symbol=symbol, currency=currency))

    result = await YahooFinancePriceProvider(transport).fetch(
        _requirement(symbol=symbol, currency=currency)
    )

    assert result.provider_symbol == symbol
    assert result.currency == currency
    assert transport.calls[0][0] == symbol


@pytest.mark.asyncio
async def test_provider_rejects_price_hint_above_persisted_precision() -> None:
    with pytest.raises(MarketEvidenceStateError):
        await YahooFinancePriceProvider(_Transport(_body(price_hint=11))).fetch(_requirement())


@pytest.mark.asyncio
@pytest.mark.parametrize("granularity", [None, "1d"])
async def test_provider_rejects_non_minute_chart(granularity: str | None) -> None:
    with pytest.raises(MarketEvidenceStateError):
        await YahooFinancePriceProvider(_Transport(_body(granularity=granularity))).fetch(
            _requirement()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b'{"chart":{"result":null,"error":{"code":"Not Found"}}}',
        b'{"chart":{"result":[{"meta":{"symbol":"VUAA.MI"}}],"error":null}}',
    ],
)
async def test_provider_rejects_unknown_or_partial_chart(body: bytes) -> None:
    with pytest.raises(MarketEvidenceStateError):
        await YahooFinancePriceProvider(_Transport(body)).fetch(_requirement())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, requirement",
    [
        (_body(symbol="VUAA.DE"), _requirement()),
        (_body(currency="USD"), _requirement()),
        (_body(observed_at=OBSERVED_AT + timedelta(hours=2)), _requirement()),
        (
            _body(observed_at=OBSERVED_AT),
            PriceRequirement(
                account_id="account-1",
                asset_id="asset-1",
                listing_id="listing-1",
                listing_currency="EUR",
                provider=PriceSource.yahoo_finance,
                provider_symbol="VUAA.MI",
                through=OBSERVED_AT + timedelta(hours=72, milliseconds=1),
            ),
        ),
    ],
)
async def test_provider_rejects_wrong_identity_future_and_stale_quote(
    body: bytes,
    requirement: PriceRequirement,
) -> None:
    with pytest.raises(MarketEvidenceStateError):
        await YahooFinancePriceProvider(_Transport(body)).fetch(requirement)
