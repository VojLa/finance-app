from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import (
    AuthenticationConfigurationError,
    AuthenticationRequiredError,
    InvalidSessionTokenError,
)
from app.auth.models import AuthenticatedPrincipal, InternalTokenClaims
from app.auth.token import InternalTokenVerifier
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.users import UserModel

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="InternalSessionToken")


def get_request_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_verified_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> InternalTokenClaims:
    """Reject missing or invalid tokens before any database dependency is opened."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationRequiredError()
    if not settings.internal_auth_secret:
        raise AuthenticationConfigurationError()

    return InternalTokenVerifier(
        secret=settings.internal_auth_secret,
        issuer=settings.internal_auth_issuer,
        audience=settings.internal_auth_audience,
        clock_skew_seconds=settings.internal_auth_clock_skew_seconds,
    ).verify(credentials.credentials)


async def get_current_principal(
    claims: Annotated[InternalTokenClaims, Depends(get_verified_token_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
    """Resolve a verified token subject against PostgreSQL."""

    user = await session.scalar(select(UserModel).where(UserModel.id == claims.sub))
    if user is None:
        raise InvalidSessionTokenError("The session token subject does not exist.")

    return AuthenticatedPrincipal(
        user_id=user.id,
        email=user.email,
        name=user.name,
        session_id=claims.jti,
    )


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]
