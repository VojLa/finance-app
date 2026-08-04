from __future__ import annotations

from datetime import date
from types import TracebackType
from typing import Any

import httpx
import pytest
from support.cnb_fx import cnb_xml

from app.modules.fx.providers.cnb_transport import HttpxCnbFxTransport
from app.modules.market_data.models import MarketEvidenceStateError

BASE_URL = "https://www.cnb.cz/test/denni_kurz.xml"


def _transport(
    handler: Any,
    *,
    max_response_bytes: int = 1_048_576,
    client_factory: Any = httpx.AsyncClient,
) -> HttpxCnbFxTransport:
    return HttpxCnbFxTransport(
        base_url=BASE_URL,
        timeout_seconds=10,
        max_response_bytes=max_response_bytes,
        user_agent="finance-app/0.1",
        transport=httpx.MockTransport(handler),
        client_factory=client_factory,
    )


@pytest.mark.asyncio
async def test_transport_makes_one_exact_bounded_request_without_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/xml; charset=utf-8"},
            content=cnb_xml(date(2026, 8, 3)),
        )

    result = await _transport(handler).fetch_daily_rates(date(2026, 8, 3))

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"{BASE_URL}?date=03.08.2026"
    assert request.method == "GET"
    assert request.headers["user-agent"] == "finance-app/0.1"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert result.content_type == "application/xml"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content_type"),
    [
        (301, "application/xml"),
        (500, "application/xml"),
        (200, None),
        (200, "text/html"),
        (200, "application/json"),
    ],
)
async def test_transport_rejects_http_and_content_type_failures(
    status: int,
    content_type: str | None,
) -> None:
    headers = {"content-type": content_type} if content_type else {}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers, content=b"<xml/>")

    with pytest.raises(MarketEvidenceStateError):
        await _transport(handler).fetch_daily_rates(date(2026, 8, 3))


@pytest.mark.asyncio
async def test_transport_rejects_oversized_or_empty_body() -> None:
    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            content=b"12345",
        )

    with pytest.raises(MarketEvidenceStateError):
        await _transport(oversized, max_response_bytes=4).fetch_daily_rates(date(2026, 8, 3))

    def empty(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/xml"}, content=b"")

    with pytest.raises(MarketEvidenceStateError):
        await _transport(empty).fetch_daily_rates(date(2026, 8, 3))


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
            headers={"content-type": "text/xml"},
            content=cnb_xml(date(2026, 8, 3)),
        )

    await _transport(handler, client_factory=client_factory).fetch_daily_rates(date(2026, 8, 3))
    assert closed == [True]


@pytest.mark.asyncio
async def test_transport_maps_timeout_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        await _transport(handler).fetch_daily_rates(date(2026, 8, 3))
    assert calls == 1
