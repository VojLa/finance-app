"""Bounded, one-shot transport for CoinGecko simple price evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.coingecko_models import CoinGeckoHttpResponse


class CoinGeckoPriceTransport(Protocol):
    async def fetch_simple_price(
        self,
        provider_symbol: str,
        quote_currency: str,
    ) -> CoinGeckoHttpResponse: ...


class HttpxCoinGeckoPriceTransport:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        demo_api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._user_agent = user_agent
        self._demo_api_key = demo_api_key
        self._transport = transport
        self._client_factory = client_factory

    async def fetch_simple_price(
        self,
        provider_symbol: str,
        quote_currency: str,
    ) -> CoinGeckoHttpResponse:
        headers = {
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        if self._demo_api_key is not None:
            headers["x-cg-demo-api-key"] = self._demo_api_key
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
                        "ids": provider_symbol,
                        "vs_currencies": quote_currency,
                        "include_last_updated_at": "true",
                        "precision": "full",
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
                    return CoinGeckoHttpResponse(
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
        except MarketEvidenceStateError:
            raise
        except httpx.HTTPError as exc:
            raise MarketEvidenceStateError() from exc
