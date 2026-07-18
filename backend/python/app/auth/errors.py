from app.shared.errors import ApplicationError


class AuthenticationRequiredError(ApplicationError):
    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__(code="authentication_required", message=message, status_code=401)


class InvalidSessionTokenError(ApplicationError):
    def __init__(self, message: str = "The session token is invalid.") -> None:
        super().__init__(code="invalid_session_token", message=message, status_code=401)


class ExpiredSessionTokenError(ApplicationError):
    def __init__(self, message: str = "The session token has expired.") -> None:
        super().__init__(code="expired_session_token", message=message, status_code=401)


class AuthenticationConfigurationError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="authentication_unavailable",
            message="Authentication is not configured.",
            status_code=503,
        )
