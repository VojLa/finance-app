from __future__ import annotations

import inspect
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.providers.twelve_data import TwelveDataExchangeRateProvider
from app.modules.fx.providers.twelve_data_models import TwelveDataFxHttpResponse
from app.modules.market_data.models import ExchangeRateRequirement, MarketEvidenceStateError


def _body(*, symbol: str = "EUR/USD", rows: str | None = None) -> bytes:
    values = rows or (
        '[{"datetime":"2026-08-03","close":"1.15320000"},'
        '{"datetime":"2026-07-31","close":"1.14750000"}]'
    )
    return f'{{"meta":{{"symbol":"{symbol}"}},"values":{values},"status":"ok"}}'.encode()


class FakeTransport:
    def __init__(self, response: TwelveDataFxHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, date]] = []

    async def fetch(
        self, from_currency: str, to_currency: str, through: date
    ) -> TwelveDataFxHttpResponse:
        self.calls.append((from_currency, to_currency, through))
        return self.response


def _requirement(
    *,
    from_currency: str = "EUR",
    to_currency: str = "USD",
    through: datetime = datetime(2026, 8, 3, 12),
    provider: ExchangeRateSource = ExchangeRateSource.twelve_data,
) -> ExchangeRateRequirement:
    return ExchangeRateRequirement(from_currency, to_currency, through, provider)


@pytest.mark.asyncio
async def test_provider_returns_one_exact_direct_observation() -> None:
    transport = FakeTransport(TwelveDataFxHttpResponse(200, "application/json", _body()))

    result = await TwelveDataExchangeRateProvider(transport).fetch(_requirement())

    assert transport.calls == [("EUR", "USD", date(2026, 8, 3))]
    assert result.from_currency == "EUR"
    assert result.to_currency == "USD"
    assert result.provider is ExchangeRateSource.twelve_data
    assert result.rate == Decimal("1.15320000")
    assert result.effective_at == datetime(2026, 8, 3)


@pytest.mark.asyncio
async def test_provider_uses_latest_nonfuture_historical_point() -> None:
    transport = FakeTransport(TwelveDataFxHttpResponse(200, "application/json", _body()))

    result = await TwelveDataExchangeRateProvider(transport).fetch(
        _requirement(through=datetime(2026, 8, 2, 18))
    )

    assert result.rate == Decimal("1.14750000")
    assert result.effective_at == datetime(2026, 7, 31)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requirement",
    [
        _requirement(from_currency="EUR", to_currency="EUR"),
        _requirement(from_currency="eur"),
        _requirement(provider=ExchangeRateSource.cnb),
        _requirement(through=datetime(2026, 8, 3, 12, 0, 0, 1)),
    ],
)
async def test_provider_rejects_invalid_or_legacy_requirement_before_http(
    requirement: ExchangeRateRequirement,
) -> None:
    transport = FakeTransport(TwelveDataFxHttpResponse(200, "application/json", _body()))
    with pytest.raises(MarketEvidenceStateError):
        await TwelveDataExchangeRateProvider(transport).fetch(requirement)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        TwelveDataFxHttpResponse(429, "application/json", b'{"status":"error"}'),
        TwelveDataFxHttpResponse(200, "text/html", b"error"),
        TwelveDataFxHttpResponse(200, "application/json", _body(symbol="USD/EUR")),
        TwelveDataFxHttpResponse(
            200,
            "application/json",
            _body(rows='[{"datetime":"2026-07-26","close":"1.1"}]'),
        ),
    ],
)
async def test_provider_fails_closed_for_quota_schema_direction_and_staleness(
    response: TwelveDataFxHttpResponse,
) -> None:
    transport = FakeTransport(response)
    with pytest.raises(MarketEvidenceStateError):
        await TwelveDataExchangeRateProvider(transport).fetch(_requirement())
    assert len(transport.calls) == 1


def test_provider_has_no_clock_database_inversion_or_pivot_boundary() -> None:
    source = inspect.getsource(TwelveDataExchangeRateProvider)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "sqlalchemy" not in source
    assert "session" not in source
    assert "CZK" not in source
    assert "inverse" not in source.lower()
