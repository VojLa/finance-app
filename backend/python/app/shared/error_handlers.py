from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.errors import ApplicationError, ErrorDetail, ErrorResponse

ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value is not None else None


def _response(*, request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def application_error_handler(request: Request, error: ApplicationError) -> JSONResponse:
    return _response(
        request=request,
        status_code=error.status_code,
        code=error.code,
        message=error.message,
    )


async def validation_error_handler(
    request: Request,
    _error: RequestValidationError,
) -> JSONResponse:
    return _response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="Request validation failed.",
    )


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    codes = {
        status.HTTP_401_UNAUTHORIZED: "unauthorized",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_503_SERVICE_UNAVAILABLE: "dependency_unavailable",
    }
    message = error.detail if isinstance(error.detail, str) else "The request could not be completed."
    return _response(
        request=request,
        status_code=error.status_code,
        code=codes.get(error.status_code, "http_error"),
        message=message,
    )


async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
    return _response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error_handler)
