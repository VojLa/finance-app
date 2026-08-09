from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import (
    AuthenticationConfigurationError,
    AuthenticationRequiredError,
    AuthenticationTransactionStateError,
    InvalidSessionTokenError,
)
from app.auth.models import AuthenticatedPrincipal, InternalTokenClaims
from app.auth.token import InternalTokenVerifier
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.users import UserModel

INTERNAL_AUTH_SERVICE_SUBJECT = "finance-app-next-auth-service"

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="InternalSessionToken",
    bearerFormat="JWT",
)


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
    """Resolve a verified subject and leave the request session idle.

    Token verification runs before the database dependency. The persisted-user
    lookup then owns one implicit read transaction, copies all ORM values into
    an application principal, and commits that read before downstream services
    establish their own transaction boundaries.
    """

    if session.in_transaction():
        raise AuthenticationTransactionStateError()

    try:
        user = await session.scalar(select(UserModel).where(UserModel.id == claims.sub))
    except SQLAlchemyError as exc:
        if session.in_transaction():
            await session.rollback()
        raise AuthenticationTransactionStateError() from exc

    if user is None:
        try:
            await session.rollback()
        except SQLAlchemyError as exc:
            raise AuthenticationTransactionStateError() from exc
        if session.in_transaction():
            raise AuthenticationTransactionStateError()
        raise InvalidSessionTokenError("The session token subject does not exist.")

    principal = AuthenticatedPrincipal(
        user_id=user.id,
        email=user.email,
        name=user.name,
        session_id=claims.jti,
    )

    try:
        await session.commit()
    except SQLAlchemyError as exc:
        if session.in_transaction():
            await session.rollback()
        raise AuthenticationTransactionStateError() from exc
    if session.in_transaction():
        raise AuthenticationTransactionStateError()

    return principal


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


def require_auth_service(
    claims: Annotated[InternalTokenClaims, Depends(get_verified_token_claims)],
) -> InternalTokenClaims:
    """Authorize the trusted Next.js adapter without pretending it is an end user."""

    if claims.sub != INTERNAL_AUTH_SERVICE_SUBJECT:
        raise InvalidSessionTokenError("The session token is not authorized for this operation.")
    return claims


AuthServiceClaims = Annotated[InternalTokenClaims, Depends(require_auth_service)]
