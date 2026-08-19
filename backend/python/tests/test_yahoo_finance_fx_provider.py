from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.providers.yahoo_finance import YahooFinanceExchangeRateProvider
from app.modules.market_data.models import ExchangeRateRequirement, MarketEvidenceStateError
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport


def _body(
    *,
    rows: str,
    symbol: str = "EURCZK=X",
    currency: str = "CZK",
) -> bytes:
    document = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol, "currency": currency, "priceHint": 8},
                    "timestamp": [1722556800, 1722816000],
                    "indicators": {"quote": [{"close": "__ROWS__"}]},
                }
            ],
            "error": None,
        }
    }
    return json.dumps(document, separators=(",", ":")).replace('"__ROWS__"', rows).encode()


class _Transport(YahooFinanceChartTransport):
    def __init__(self, body: bytes | dict[str, bytes]) -> None:
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
        body = self.body[symbol] if isinstance(self.body, dict) else self.body
        return YahooFinanceHttpResponse(200, "application/json", body)


class _ConcurrentTransport(YahooFinanceChartTransport):
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.calls: list[str] = []
        self.active = 0
        self.maximum_active = 0
        self.reached_parallelism = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        assert start < end
        assert interval == "1d"
        self.calls.append(symbol)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.active >= 4:
            self.reached_parallelism.set()
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return YahooFinanceHttpResponse(200, "application/json", self.bodies[symbol])


def _requirement(through: datetime) -> ExchangeRateRequirement:
    return ExchangeRateRequirement("EUR", "CZK", through, ExchangeRateSource.yahoo_finance)


@pytest.mark.asyncio
async def test_fx_provider_batches_historical_direct_pair_once() -> None:
    transport = _Transport(_body(rows='["25.11000000","25.22000000"]'))
    provider = YahooFinanceExchangeRateProvider(transport)
    requirements = (_requirement(datetime(2024, 8, 2, 12)), _requirement(datetime(2024, 8, 5, 12)))

    result = await provider.fetch_many(requirements)

    assert len(transport.calls) == 1
    assert transport.calls[0][0] == "EURCZK=X"
    assert transport.calls[0][3] == "1d"
    assert tuple(item.rate for item in result) == (Decimal("25.11000000"), Decimal("25.22000000"))


@pytest.mark.asyncio
async def test_fx_provider_rejects_missing_historical_point_for_any_requirement() -> None:
    provider = YahooFinanceExchangeRateProvider(_Transport(_body(rows='[null,"25.22000000"]')))
    with pytest.raises(MarketEvidenceStateError):
        await provider.fetch_many((_requirement(datetime(2024, 8, 2, 12)),))


@pytest.mark.asyncio
async def test_fx_provider_bounds_overlapping_exact_pair_groups_and_preserves_input_order() -> None:
    pairs = (
        ("EEE", "FFF"),
        ("AAA", "BBB"),
        ("GGG", "HHH"),
        ("III", "JJJ"),
        ("CCC", "DDD"),
    )
    bodies = {
        f"{from_currency}{to_currency}=X": _body(
            rows='["1.23456789","1.23456789"]',
            symbol=f"{from_currency}{to_currency}=X",
            currency=to_currency,
        )
        for from_currency, to_currency in pairs
    }
    transport = _ConcurrentTransport(bodies)
    provider = YahooFinanceExchangeRateProvider(transport)
    requirements = tuple(
        ExchangeRateRequirement(
            from_currency,
            to_currency,
            datetime(2024, 8, 5, 12),
            ExchangeRateSource.yahoo_finance,
        )
        for from_currency, to_currency in pairs
    )

    fetch = asyncio.create_task(provider.fetch_many(requirements))
    await asyncio.wait_for(transport.reached_parallelism.wait(), timeout=1)

    assert transport.maximum_active == 4
    transport.release.set()
    result = await fetch

    assert transport.maximum_active == 4
    assert set(transport.calls) == {
        f"{from_currency}{to_currency}=X" for from_currency, to_currency in pairs
    }
    assert tuple((item.from_currency, item.to_currency) for item in result) == pairs


@pytest.mark.parametrize(
    ("to_currency", "canonical_symbol", "rate"),
    (
        ("EUR", "EUR=X", "0.92000000"),
        ("CZK", "CZK=X", "22.50000000"),
    ),
)
@pytest.mark.asyncio
async def test_usd_base_uses_yahoo_canonical_direct_symbol(
    to_currency: str,
    canonical_symbol: str,
    rate: str,
) -> None:
    transport = _Transport(
        _body(
            rows=f'["{rate}","{rate}"]',
            symbol=canonical_symbol,
            currency=to_currency,
        )
    )
    provider = YahooFinanceExchangeRateProvider(transport)
    requirement = ExchangeRateRequirement(
        "USD",
        to_currency,
        datetime(2024, 8, 5, 12),
        ExchangeRateSource.yahoo_finance,
    )

    result = await provider.fetch(requirement)

    assert [call[0] for call in transport.calls] == [canonical_symbol]
    assert (result.from_currency, result.to_currency, result.rate) == (
        "USD",
        to_currency,
        Decimal(rate),
    )


@pytest.mark.asyncio
async def test_usd_base_rejects_noncanonical_response_identity() -> None:
    transport = _Transport(
        _body(
            rows='["0.92000000","0.92000000"]',
            symbol="USDEUR=X",
            currency="EUR",
        )
    )
    provider = YahooFinanceExchangeRateProvider(transport)

    with pytest.raises(MarketEvidenceStateError):
        await provider.fetch(
            ExchangeRateRequirement(
                "USD",
                "EUR",
                datetime(2024, 8, 5, 12),
                ExchangeRateSource.yahoo_finance,
            )
        )

    assert [call[0] for call in transport.calls] == ["EUR=X"]


@pytest.mark.parametrize("surface", ("portfolio", "dashboard"))
@pytest.mark.asyncio
async def test_current_surfaces_share_one_direct_canonical_fx_batch_without_fallback(
    surface: str,
) -> None:
    through = datetime(2024, 8, 5, 12)
    bodies = {
        "CZKEUR=X": _body(
            rows='["0.04000000","0.04100000"]',
            symbol="CZKEUR=X",
            currency="EUR",
        ),
        "EURCZK=X": _body(rows='["25.00000000","24.39000000"]'),
        "CZK=X": _body(
            rows='["22.00000000","22.50000000"]',
            symbol="CZK=X",
            currency="CZK",
        ),
        "EUR=X": _body(
            rows='["0.91000000","0.92000000"]',
            symbol="EUR=X",
            currency="EUR",
        ),
    }
    transport = _Transport(bodies)
    provider = YahooFinanceExchangeRateProvider(transport)
    requirements = tuple(
        ExchangeRateRequirement(
            from_currency,
            to_currency,
            through,
            ExchangeRateSource.yahoo_finance,
        )
        for from_currency, to_currency in (
            ("CZK", "EUR"),
            ("EUR", "CZK"),
            ("USD", "CZK"),
            ("USD", "EUR"),
        )
    )

    result = await provider.fetch_many(requirements)

    assert surface in {"portfolio", "dashboard"}
    assert [call[0] for call in transport.calls] == [
        "CZKEUR=X",
        "EURCZK=X",
        "CZK=X",
        "EUR=X",
    ]
    assert tuple((item.from_currency, item.to_currency) for item in result) == tuple(
        (item.from_currency, item.to_currency) for item in requirements
    )
    assert "USDCZK=X" not in bodies
    assert "USDEUR=X" not in bodies
    assert "CZKUSD=X" not in bodies
    assert "EURUSD=X" not in bodies
