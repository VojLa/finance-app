from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApplicationError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(ApplicationError):
    def __init__(self, message: str = "Resource was not found.") -> None:
        super().__init__(code="not_found", message=message, status_code=404)


class ConflictError(ApplicationError):
    def __init__(self, message: str = "The request conflicts with the current state.") -> None:
        super().__init__(code="conflict", message=message, status_code=409)


class UnauthorizedError(ApplicationError):
    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__(code="unauthorized", message=message, status_code=401)


class ForbiddenError(ApplicationError):
    def __init__(self, message: str = "The operation is not permitted.") -> None:
        super().__init__(code="forbidden", message=message, status_code=403)


class DependencyUnavailableError(ApplicationError):
    def __init__(self, message: str = "A required dependency is unavailable.") -> None:
        super().__init__(code="dependency_unavailable", message=message, status_code=503)
