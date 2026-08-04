from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from support.cnb_fx import cnb_xml

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.providers.cnb import CnbExchangeRateProvider
from app.modules.fx.providers.cnb_models import CnbFxHttpResponse
from app.modules.market_data.models import ExchangeRateRequirement, MarketEvidenceStateError


class FakeTransport:
    def __init__(self, response: CnbFxHttpResponse) -> None:
        self.response = response
        self.calls: list[date] = []

    async def fetch_daily_rates(self, through_date: date) -> CnbFxHttpResponse:
        self.calls.append(through_date)
        return self.response


def _response(
    published: date,
    rows: tuple[tuple[str, str, str], ...] = (("EUR", "1", "24,500"),),
) -> CnbFxHttpResponse:
    return CnbFxHttpResponse(200, "application/xml", cnb_xml(published, rows))


def _requirement(
    *,
    through: datetime = datetime(2026, 8, 3, 12),
    from_currency: str = "EUR",
    to_currency: str = "CZK",
    provider: ExchangeRateSource = ExchangeRateSource.cnb,
) -> ExchangeRateRequirement:
    return ExchangeRateRequirement(from_currency, to_currency, through, provider)


@pytest.mark.asyncio
async def test_provider_returns_exact_direct_observation_from_publication_date() -> None:
    transport = FakeTransport(_response(date(2026, 8, 3), (("JPY", "100", "14,321"),)))

    result = await CnbExchangeRateProvider(transport).fetch(_requirement(from_currency="JPY"))

    assert transport.calls == [date(2026, 8, 3)]
    assert result.from_currency == "JPY"
    assert result.to_currency == "CZK"
    assert result.provider is ExchangeRateSource.cnb
    assert result.rate == Decimal("0.14321")
    assert result.effective_at == datetime(2026, 8, 3)


@pytest.mark.asyncio
async def test_provider_accepts_fresh_weekend_publication_without_fallback_request() -> None:
    transport = FakeTransport(_response(date(2026, 7, 31)))

    result = await CnbExchangeRateProvider(transport).fetch(
        _requirement(through=datetime(2026, 8, 2, 18))
    )

    assert result.effective_at == datetime(2026, 7, 31)
    assert transport.calls == [date(2026, 8, 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "published",
    [date(2026, 8, 4), date(2026, 7, 26)],
)
async def test_provider_rejects_future_or_stale_document(published: date) -> None:
    transport = FakeTransport(_response(published))
    with pytest.raises(MarketEvidenceStateError):
        await CnbExchangeRateProvider(transport).fetch(_requirement())
    assert transport.calls == [date(2026, 8, 3)]


@pytest.mark.asyncio
async def test_provider_rejects_missing_currency_and_nonrepresentable_rate() -> None:
    missing = FakeTransport(_response(date(2026, 8, 3), (("USD", "1", "21,000"),)))
    with pytest.raises(MarketEvidenceStateError):
        await CnbExchangeRateProvider(missing).fetch(_requirement())

    repeating = FakeTransport(_response(date(2026, 8, 3), (("EUR", "3", "1,000"),)))
    with pytest.raises(MarketEvidenceStateError):
        await CnbExchangeRateProvider(repeating).fetch(_requirement())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requirement",
    [
        _requirement(from_currency="CZK"),
        _requirement(to_currency="EUR"),
        _requirement(provider=ExchangeRateSource.ecb),
        _requirement(from_currency="eur"),
        _requirement(through=datetime(2026, 8, 3, 12, 0, 0, 1)),
    ],
)
async def test_provider_rejects_unsupported_requirement_before_http(
    requirement: ExchangeRateRequirement,
) -> None:
    transport = FakeTransport(_response(date(2026, 8, 3)))
    with pytest.raises(MarketEvidenceStateError):
        await CnbExchangeRateProvider(transport).fetch(requirement)
    assert transport.calls == []
