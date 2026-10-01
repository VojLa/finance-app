"""Bounded one-shot transport for Twelve Data /quote evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from app.db.models.enums import MarketDataFailureReason
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.provider_failure import ProviderFailure
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
            raise ProviderFailure(MarketDataFailureReason.provider_identity_conflict)
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
                    retry_after = _sanitized_retry_after(response.headers.get("retry-after"))
                    raw_content_type = response.headers.get("content-type")
                    content_type = (
                        raw_content_type.partition(";")[0].strip().lower()
                        if raw_content_type
                        else None
                    )
                    if response.status_code != 200:
                        return TwelveDataHttpResponse(
                            response.status_code, content_type or "", b"", retry_after
                        )
                    if content_type != "application/json":
                        raise ProviderFailure(MarketDataFailureReason.incomplete_response)
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise ProviderFailure(MarketDataFailureReason.incomplete_response)
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if not body:
                        raise ProviderFailure(MarketDataFailureReason.incomplete_response)
                    return TwelveDataHttpResponse(
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                        retry_after=retry_after,
                    )
        except MarketEvidenceStateError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderFailure(MarketDataFailureReason.timeout) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure(MarketDataFailureReason.server_error) from exc


def _sanitized_retry_after(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if (
        len(value) > 128
        or not value.isascii()
        or any(ord(char) < 32 or ord(char) > 126 for char in value)
    ):
        return None
    return value or None
