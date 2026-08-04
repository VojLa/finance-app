from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx
import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.coingecko_transport import (
    HttpxCoinGeckoPriceTransport,
)

BASE_URL = "https://api.coingecko.com/api/v3/simple/price"


def _transport(
    handler: Any,
    *,
    max_response_bytes: int = 1_048_576,
    demo_api_key: str | None = None,
    client_factory: Any = httpx.AsyncClient,
) -> HttpxCoinGeckoPriceTransport:
    return HttpxCoinGeckoPriceTransport(
        base_url=BASE_URL,
        timeout_seconds=10,
        max_response_bytes=max_response_bytes,
        user_agent="finance-app/0.1",
        demo_api_key=demo_api_key,
        transport=httpx.MockTransport(handler),
        client_factory=client_factory,
    )


@pytest.mark.asyncio
async def test_transport_makes_one_exact_request_without_credentials_or_cookies() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            content=b'{"bitcoin":{"eur":1,"last_updated_at":1785841140}}',
        )

    result = await _transport(handler).fetch_simple_price("bitcoin", "eur")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        f"{BASE_URL}?ids=bitcoin&vs_currencies=eur&include_last_updated_at=true&precision=full"
    )
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"] == "finance-app/0.1"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert "x-cg-demo-api-key" not in request.headers
    assert result.content_type == "application/json"


@pytest.mark.asyncio
async def test_transport_sends_optional_demo_key_only_in_header() -> None:
    secret = "demo-secret-value"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-cg-demo-api-key"] == secret
        assert secret not in str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"{}",
        )

    result = await _transport(handler, demo_api_key=secret).fetch_simple_price(
        "bitcoin",
        "eur",
    )
    assert secret not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content_type"),
    [
        (204, "application/json"),
        (301, "application/json"),
        (404, "application/json"),
        (429, "application/json"),
        (500, "application/json"),
        (200, None),
        (200, "text/html"),
        (200, "application/xml"),
    ],
)
async def test_transport_rejects_status_or_content_type(
    status: int,
    content_type: str | None,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        headers = {"content-type": content_type} if content_type else {}
        return httpx.Response(status, headers=headers, content=b"{}")

    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        await _transport(handler).fetch_simple_price("bitcoin", "eur")
    assert calls == 1


@pytest.mark.asyncio
async def test_transport_rejects_empty_and_oversized_body() -> None:
    def empty(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"",
        )

    with pytest.raises(MarketEvidenceStateError):
        await _transport(empty).fetch_simple_price("bitcoin", "eur")

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"12345",
        )

    with pytest.raises(MarketEvidenceStateError):
        await _transport(oversized, max_response_bytes=4).fetch_simple_price(
            "bitcoin",
            "eur",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "network"])
async def test_transport_maps_http_failures_without_retry(failure: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive failure", request=request)
        raise httpx.ConnectError("sensitive failure", request=request)

    with pytest.raises(
        MarketEvidenceStateError,
        match=r"Market evidence is unavailable\.",
    ):
        await _transport(handler, demo_api_key="do-not-leak").fetch_simple_price(
            "bitcoin",
            "eur",
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_transport_closes_short_lived_client() -> None:
    closed: list[bool] = []

    class TrackingClient(httpx.AsyncClient):
        async def __aexit__(
            self,
            exc_type: type[BaseException] | None = None,
            exc_value: BaseException | None = None,
            traceback: TracebackType | None = None,
        ) -> None:
            await super().__aexit__(exc_type, exc_value, traceback)
            closed.append(True)

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        return TrackingClient(**kwargs)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"{}",
        )

    await _transport(handler, client_factory=client_factory).fetch_simple_price(
        "bitcoin",
        "eur",
    )
    assert closed == [True]
