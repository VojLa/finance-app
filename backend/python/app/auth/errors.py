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


class AuthenticationTransactionStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="authentication_unavailable",
            message="Authentication is temporarily unavailable.",
            status_code=503,
        )


class InvalidCredentialsError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_credentials",
            message="The email or password is invalid.",
            status_code=401,
        )


class EmailAlreadyRegisteredError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="email_already_registered",
            message="The email address is already registered.",
            status_code=409,
        )


class CurrentPasswordInvalidError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="current_password_invalid",
            message="The current password is invalid.",
            status_code=409,
        )
