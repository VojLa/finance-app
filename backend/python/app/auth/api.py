from fastapi import APIRouter

from app.auth.dependencies import CurrentPrincipal
from app.auth.models import CurrentUserResponse
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
