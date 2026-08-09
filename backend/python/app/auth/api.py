from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthServiceClaims, CurrentPrincipal
from app.auth.models import (
    AuthenticatedUserResponse,
    CredentialVerificationRequest,
    CurrentUserResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    UserRegistrationRequest,
)
from app.auth.service import AuthService
from app.db.connection import get_db_session
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid, or expired session token."},
        503: {"model": ErrorResponse, "description": "Authentication is not configured."},
    },
)
async def get_current_user(principal: CurrentPrincipal) -> CurrentUserResponse:
    """Return the database-backed identity represented by the internal token."""

    return CurrentUserResponse(
        id=principal.user_id,
        email=principal.email,
        name=principal.name,
    )


@router.post(
    "/credentials/verify",
    response_model=AuthenticatedUserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials or service token."},
        422: {"model": ErrorResponse, "description": "Invalid request."},
        503: {"model": ErrorResponse, "description": "Authentication is unavailable."},
    },
)
async def verify_credentials(
    payload: CredentialVerificationRequest,
    _service: AuthServiceClaims,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
) -> AuthenticatedUserResponse:
    result = await AuthService(session).verify_credentials(payload)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/register",
    response_model=AuthenticatedUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid service token."},
        409: {"model": ErrorResponse, "description": "Email is already registered."},
        422: {"model": ErrorResponse, "description": "Invalid request."},
        503: {"model": ErrorResponse, "description": "Authentication is unavailable."},
    },
)
async def register_user(
    payload: UserRegistrationRequest,
    _service: AuthServiceClaims,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
) -> AuthenticatedUserResponse:
    result = await AuthService(session).register(payload)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.put(
    "/password",
    response_model=PasswordChangeResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Authentication is required."},
        409: {"model": ErrorResponse, "description": "Current password is invalid."},
        422: {"model": ErrorResponse, "description": "Invalid request."},
        503: {"model": ErrorResponse, "description": "Authentication is unavailable."},
    },
)
async def change_password(
    payload: PasswordChangeRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
) -> PasswordChangeResponse:
    await AuthService(session).change_password(principal=principal, payload=payload)
    response.headers["Cache-Control"] = "no-store"
    return PasswordChangeResponse(ok=True)
