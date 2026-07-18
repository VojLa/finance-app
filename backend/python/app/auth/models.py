from pydantic import BaseModel, ConfigDict


class InternalTokenClaims(BaseModel):
    """Validated claims accepted from the trusted Next.js session bridge."""

    model_config = ConfigDict(extra="forbid")

    sub: str
    email: str | None = None
    iss: str
    aud: str | list[str]
    iat: int
    exp: int
    jti: str | None = None


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
