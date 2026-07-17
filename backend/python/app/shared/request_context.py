from __future__ import annotations

from time import perf_counter
from uuid import UUID, uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"


def _request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = _request_id(request.headers.get(REQUEST_ID_HEADER))
        started_at = perf_counter()
        request.state.request_id = request_id
        request.state.request_started_at = started_at

        settings = getattr(request.app.state, "settings", None)
        environment = getattr(settings, "environment", "unknown")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            environment=environment,
        )

        try:
            response = await call_next(request)
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id
            structlog.get_logger("http").info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
