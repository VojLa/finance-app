from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from app.modules.fx.providers.twelve_data_transport import HttpxTwelveDataFxTransport

BASE_URL = "https://api.twelvedata.test/time_series"


def _transport(handler: Any, *, maximum: int = 1_048_576) -> HttpxTwelveDataFxTransport:
    return HttpxTwelveDataFxTransport(
        base_url=BASE_URL,
        api_key="secret-test-key",
        timeout_seconds=10,
        max_response_bytes=maximum,
        user_agent="finance-app/0.1",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_transport_requests_only_exact_direct_pair_and_bounded_history() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            content=b'{"status":"ok"}',
        )

    result = await _transport(handler).fetch("EUR", "USD", date(2026, 8, 3))

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.params["symbol"] == "EUR/USD"
    assert request.url.params["interval"] == "1day"
    assert request.url.params["start_date"] == "2026-07-27"
    assert request.url.params["end_date"] == "2026-08-04"
    assert request.url.params["outputsize"] == "8"
    assert "apikey" not in request.url.params
    assert request.headers["authorization"] == "apikey secret-test-key"
    assert "secret-test-key" not in str(request.url)
    assert "cookie" not in request.headers
    assert result.status_code == 200
    assert result.content_type == "application/json"


@pytest.mark.asyncio
async def test_transport_maps_network_and_oversized_responses_without_retry() -> None:
    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    unavailable_result = await _transport(unavailable).fetch("EUR", "USD", date(2026, 8, 3))
    assert calls == 1
    assert unavailable_result.status_code == 503
    assert unavailable_result.body == b""

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"12345")

    oversized_result = await _transport(oversized, maximum=4).fetch("EUR", "USD", date(2026, 8, 3))
    assert oversized_result.status_code == 503
    assert oversized_result.body == b""


@pytest.mark.asyncio
async def test_transport_without_api_key_fails_before_http() -> None:
    calls = 0

    def unexpected(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    transport = HttpxTwelveDataFxTransport(
        base_url=BASE_URL,
        api_key=None,
        timeout_seconds=10,
        max_response_bytes=1024,
        user_agent="finance-app/0.1",
        transport=httpx.MockTransport(unexpected),
    )
    result = await transport.fetch("EUR", "USD", date(2026, 8, 3))

    assert calls == 0
    assert result.status_code == 503
