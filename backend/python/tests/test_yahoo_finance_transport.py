from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.yahoo_finance_transport import HttpxYahooFinanceChartTransport

BASE_URL = "https://query1.finance.yahoo.test/v8/finance/chart"
START = datetime(2026, 8, 3, 12)
END = datetime(2026, 8, 4, 12)


def _transport(handler: Any, *, maximum: int = 1_048_576) -> HttpxYahooFinanceChartTransport:
    return HttpxYahooFinanceChartTransport(
        base_url=BASE_URL,
        timeout_seconds=10,
        max_response_bytes=maximum,
        user_agent="finance-app/0.1",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_transport_requests_one_encoded_chart_without_redirect_or_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "application/json; charset=utf-8"}, content=b"{}"
        )

    result = await _transport(handler).fetch_chart("EURCZK=X", start=START, end=END, interval="1d")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.raw_path.startswith(b"/v8/finance/chart/EURCZK%3DX?")
    assert request.url.params["interval"] == "1d"
    assert request.url.params["period1"] == str(int(START.replace(tzinfo=UTC).timestamp()))
    assert request.url.params["period2"] == str(int(END.replace(tzinfo=UTC).timestamp()))
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert result.content_type == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://elsewhere.test"}),
        httpx.Response(429, headers={"content-type": "application/json"}),
        httpx.Response(200, headers={"content-type": "text/html"}, content=b"bad"),
    ],
)
async def test_transport_rejects_redirect_quota_and_wrong_content_type(
    response: httpx.Response,
) -> None:
    with pytest.raises(MarketEvidenceStateError):
        await _transport(lambda _: response).fetch_chart(
            "VUAA.MI", start=START, end=END, interval="1m"
        )


@pytest.mark.asyncio
async def test_transport_rejects_oversized_or_network_response_without_retry() -> None:
    calls = 0

    def oversized(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"12345")

    with pytest.raises(MarketEvidenceStateError):
        await _transport(oversized, maximum=4).fetch_chart(
            "VUAA.MI", start=START, end=END, interval="1m"
        )
    assert calls == 1
