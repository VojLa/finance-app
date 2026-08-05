from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx
import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.twelve_data_identity import TwelveDataQuoteIdentity
from app.modules.prices.providers.twelve_data_transport import (
    HttpxTwelveDataPriceTransport,
)

BASE_URL = "https://api.twelvedata.com/quote"
IDENTITY = TwelveDataQuoteIdentity("AAPL", "XNAS")


def _transport(
    handler: Any,
    *,
    api_key: str | None = "server-secret",
    max_response_bytes: int = 1_048_576,
    client_factory: Any = httpx.AsyncClient,
) -> HttpxTwelveDataPriceTransport:
    return HttpxTwelveDataPriceTransport(
        base_url=BASE_URL,
        timeout_seconds=10,
        max_response_bytes=max_response_bytes,
        user_agent="finance-app/0.1",
        api_key=api_key,
        transport=httpx.MockTransport(handler),
        client_factory=client_factory,
    )


@pytest.mark.asyncio
async def test_transport_makes_one_exact_header_authenticated_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            content=b"{}",
        )

    result = await _transport(handler).fetch_quote(IDENTITY)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?", maxsplit=1)[0] == BASE_URL
    assert request.url.params.multi_items() == [
        ("symbol", "AAPL"),
        ("mic_code", "XNAS"),
        ("interval", "1min"),
        ("timezone", "UTC"),
        ("format", "JSON"),
        ("prepost", "false"),
        ("dp", "10"),
    ]
    assert "apikey" not in request.url.params
    assert request.headers["authorization"] == "apikey server-secret"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"] == "finance-app/0.1"
    assert "cookie" not in request.headers
    assert result.content_type == "application/json"
    assert "server-secret" not in repr(result)


@pytest.mark.asyncio
async def test_missing_key_fails_before_client_or_http() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("HTTP must not run")

    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        await _transport(handler, api_key=None).fetch_quote(IDENTITY)
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content_type"),
    [
        (204, "application/json"),
        (301, "application/json"),
        (400, "application/json"),
        (401, "application/json"),
        (403, "application/json"),
        (404, "application/json"),
        (414, "application/json"),
        (429, "application/json"),
        (500, "application/json"),
        (200, None),
        (200, "text/html"),
        (200, "application/xml"),
        (200, "text/csv"),
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
        await _transport(handler).fetch_quote(IDENTITY)
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
        await _transport(empty).fetch_quote(IDENTITY)

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"12345",
        )

    with pytest.raises(MarketEvidenceStateError):
        await _transport(oversized, max_response_bytes=4).fetch_quote(IDENTITY)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "network"])
async def test_transport_maps_http_failures_without_retry_or_secret_leak(
    failure: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("server-secret", request=request)
        raise httpx.ConnectError("server-secret", request=request)

    with pytest.raises(MarketEvidenceStateError, match=r"Market evidence is unavailable\.") as exc:
        await _transport(handler).fetch_quote(IDENTITY)
    assert calls == 1
    assert "server-secret" not in str(exc.value)


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
        assert kwargs["follow_redirects"] is False
        assert "cookies" not in kwargs
        return TrackingClient(**kwargs)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"{}",
        )

    await _transport(handler, client_factory=client_factory).fetch_quote(IDENTITY)
    assert closed == [True]
