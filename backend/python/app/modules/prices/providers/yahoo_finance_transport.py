"""Bounded HTTPS transport for one exact Yahoo Finance chart symbol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse


class YahooFinanceChartTransport(Protocol):
    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse: ...


class HttpxYahooFinanceChartTransport:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._user_agent = user_agent
        self._transport = transport
        self._client_factory = client_factory

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is not None
            or end.tzinfo is not None
            or start >= end
            or interval not in {"1m", "30m", "1d"}
        ):
            raise MarketEvidenceStateError()
        try:
            period1 = int(start.replace(tzinfo=UTC).timestamp())
            period2 = int(end.replace(tzinfo=UTC).timestamp())
        except (OverflowError, OSError, ValueError) as exc:
            raise MarketEvidenceStateError() from exc
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers={"Accept": "application/json", "User-Agent": self._user_agent},
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url}/{quote(symbol, safe='')}",
                    params={"period1": str(period1), "period2": str(period2), "interval": interval},
                ) as response:
                    content_type = (
                        response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    )
                    if response.status_code != 200 or content_type != "application/json":
                        raise MarketEvidenceStateError()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise MarketEvidenceStateError()
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if not body:
                        raise MarketEvidenceStateError()
                    return YahooFinanceHttpResponse(response.status_code, content_type, body)
        except MarketEvidenceStateError:
            raise
        except httpx.HTTPError as exc:
            raise MarketEvidenceStateError() from exc


__all__ = ["HttpxYahooFinanceChartTransport", "YahooFinanceChartTransport"]
