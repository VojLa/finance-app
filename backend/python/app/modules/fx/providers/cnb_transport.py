"""Bounded, one-shot HTTP transport for official CNB daily XML."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol

import httpx

from app.modules.fx.providers.cnb_models import CnbFxHttpResponse
from app.modules.market_data.models import MarketEvidenceStateError

_ALLOWED_XML_CONTENT_TYPES = frozenset({"application/xml", "text/xml"})


class CnbFxTransport(Protocol):
    async def fetch_daily_rates(self, through_date: date) -> CnbFxHttpResponse: ...


class HttpxCnbFxTransport:
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

    async def fetch_daily_rates(self, through_date: date) -> CnbFxHttpResponse:
        if type(through_date) is not date:
            raise MarketEvidenceStateError()
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers={
                    "Accept": "application/xml, text/xml",
                    "User-Agent": self._user_agent,
                },
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET",
                    self._base_url,
                    params={"date": through_date.strftime("%d.%m.%Y")},
                ) as response:
                    raw_content_type = response.headers.get("content-type")
                    content_type = (
                        raw_content_type.partition(";")[0].strip().lower()
                        if raw_content_type
                        else None
                    )
                    if (
                        response.status_code != 200
                        or content_type not in _ALLOWED_XML_CONTENT_TYPES
                    ):
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
                    return CnbFxHttpResponse(
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
        except MarketEvidenceStateError:
            raise
        except httpx.HTTPError as exc:
            raise MarketEvidenceStateError() from exc
