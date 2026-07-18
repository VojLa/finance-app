from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr


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
