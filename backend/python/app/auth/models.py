from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.auth.validation import normalize_email, validate_new_password, validate_password_bytes


class InternalTokenClaims(BaseModel):
    """Validated claims accepted from the trusted Next.js session bridge."""

    model_config = ConfigDict(extra="forbid")

    sub: StrictStr
    email: StrictStr | None = None
    iss: StrictStr
    aud: StrictStr | list[StrictStr]
    iat: StrictInt
    exp: StrictInt
    jti: StrictStr | None = None


class AuthenticatedPrincipal(BaseModel):
    """Application-facing identity independent of the token transport."""

    user_id: str
    email: str
    name: str | None = None
    session_id: str | None = None


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None


class CredentialVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email_value(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password_value(cls, value: str) -> str:
        return validate_password_bytes(value)


class UserRegistrationRequest(CredentialVerificationRequest):
    name: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("password")
    @classmethod
    def validate_new_password_value(cls, value: str) -> str:
        return validate_new_password(value)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str

    @field_validator("current_password")
    @classmethod
    def validate_current_password_value(cls, value: str) -> str:
        return validate_password_bytes(value)

    @field_validator("new_password")
    @classmethod
    def validate_new_password_value(cls, value: str) -> str:
        return validate_new_password(value)


class AuthenticatedUserResponse(CurrentUserResponse):
    pass


class PasswordChangeResponse(BaseModel):
    ok: bool
