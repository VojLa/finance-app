"""Bounded HTTPS transport for Twelve Data direct FX history."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import httpx

from app.modules.fx.providers.twelve_data_models import TwelveDataFxHttpResponse


class TwelveDataFxTransport(Protocol):
    async def fetch(
        self, from_currency: str, to_currency: str, through: date
    ) -> TwelveDataFxHttpResponse: ...


class HttpxTwelveDataFxTransport:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._maximum = max_response_bytes
        self._user_agent = user_agent
        self._transport = transport

    async def fetch(
        self, from_currency: str, to_currency: str, through: date
    ) -> TwelveDataFxHttpResponse:
        if self._api_key is None:
            return TwelveDataFxHttpResponse(503, "", b"")
        params = {
            "symbol": f"{from_currency}/{to_currency}",
            "interval": "1day",
            "start_date": (through - timedelta(days=7)).isoformat(),
            "end_date": (through + timedelta(days=1)).isoformat(),
            "outputsize": "8",
            "order": "DESC",
            "timezone": "UTC",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Authorization": f"apikey {self._api_key}",
                },
            ) as client:
                async with client.stream("GET", self._base_url, params=params) as response:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._maximum:
                            return TwelveDataFxHttpResponse(503, "", b"")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    return TwelveDataFxHttpResponse(response.status_code, content_type, body)
        except httpx.HTTPError:
            return TwelveDataFxHttpResponse(503, "", b"")
