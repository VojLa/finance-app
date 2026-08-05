"""Bounded one-shot transport for Twelve Data /quote evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.twelve_data_identity import TwelveDataQuoteIdentity
from app.modules.prices.providers.twelve_data_models import TwelveDataHttpResponse


class TwelveDataPriceTransport(Protocol):
    async def fetch_quote(
        self,
        identity: TwelveDataQuoteIdentity,
    ) -> TwelveDataHttpResponse: ...


class HttpxTwelveDataPriceTransport:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._user_agent = user_agent
        self._api_key = api_key
        self._transport = transport
        self._client_factory = client_factory

    async def fetch_quote(
        self,
        identity: TwelveDataQuoteIdentity,
    ) -> TwelveDataHttpResponse:
        if self._api_key is None:
            raise MarketEvidenceStateError()
        headers = {
            "Accept": "application/json",
            "Authorization": f"apikey {self._api_key}",
            "User-Agent": self._user_agent,
        }
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers=headers,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET",
                    self._base_url,
                    params={
                        "symbol": identity.symbol,
                        "mic_code": identity.mic_code,
                        "interval": "1min",
                        "timezone": "UTC",
                        "format": "JSON",
                        "prepost": "false",
                        "dp": "10",
                    },
                ) as response:
                    raw_content_type = response.headers.get("content-type")
                    content_type = (
                        raw_content_type.partition(";")[0].strip().lower()
                        if raw_content_type
                        else None
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
                    return TwelveDataHttpResponse(
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
        except MarketEvidenceStateError:
            raise
        except httpx.HTTPError as exc:
            raise MarketEvidenceStateError() from exc
