from types import SimpleNamespace
from unittest.mock import AsyncMock

import bcrypt
import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import INTERNAL_AUTH_SERVICE_SUBJECT, require_auth_service
from app.auth.errors import (
    CurrentPasswordInvalidError,
    InvalidCredentialsError,
    InvalidSessionTokenError,
)
from app.auth.models import (
    AuthenticatedPrincipal,
    CredentialVerificationRequest,
    InternalTokenClaims,
    PasswordChangeRequest,
    UserRegistrationRequest,
)
from app.auth.service import AuthService


def _claims(subject: str) -> InternalTokenClaims:
    return InternalTokenClaims(
        sub=subject,
        email=None,
        iss="finance-app-next",
        aud="finance-app-python",
        iat=1,
        exp=2,
        jti="token-1",
    )


def test_auth_service_dependency_accepts_only_the_dedicated_subject() -> None:
    claims = _claims(INTERNAL_AUTH_SERVICE_SUBJECT)
    assert require_auth_service(claims) is claims

    with pytest.raises(InvalidSessionTokenError):
        require_auth_service(_claims("user-1"))


def test_auth_inputs_normalize_identity_and_enforce_bcrypt_byte_boundary() -> None:
    request = UserRegistrationRequest(
        email="  USER@Example.COM ",
        password="password-1",
        name="  Test User  ",
    )
    assert request.email == "user@example.com"
    assert request.name == "Test User"

    with pytest.raises(ValidationError):
        UserRegistrationRequest(email="not-an-email", password="password-1")
    with pytest.raises(ValidationError):
        UserRegistrationRequest(email="user@example.com", password="short")
    with pytest.raises(ValidationError):
        UserRegistrationRequest(email="user@example.com", password="ž" * 37)


@pytest.mark.asyncio
async def test_credential_verification_accepts_a_bcryptjs_hash_and_closes_read_transaction() -> (
    None
):
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = SimpleNamespace(
        id="user-1",
        email="user@example.com",
        name="User",
        password_hash="$2b$12$J8Ufcs38lSf/xbQcSXw8ouVpLX3WKTJsUDRBQTMjgpN2Lrx1Sh0..",
    )

    response = await AuthService(session).verify_credentials(
        CredentialVerificationRequest(
            email="user@example.com",
            password="legacy-password",
        )
    )

    assert response.model_dump() == {
        "id": "user-1",
        "email": "user@example.com",
        "name": "User",
    }
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_credentials_use_one_safe_error_for_missing_and_wrong_password() -> None:
    for persisted_user in [
        None,
        SimpleNamespace(password_hash=bcrypt.hashpw(b"right-password", bcrypt.gensalt()).decode()),
    ]:
        session = AsyncMock(spec=AsyncSession)
        session.scalar.return_value = persisted_user
        with pytest.raises(InvalidCredentialsError):
            await AuthService(session).verify_credentials(
                CredentialVerificationRequest(
                    email="missing@example.com",
                    password="wrong-password",
                )
            )
        session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_password_change_locks_user_and_rolls_back_on_invalid_current_password() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = SimpleNamespace(
        password_hash=bcrypt.hashpw(b"right-password", bcrypt.gensalt()).decode(),
        updated_at=None,
    )

    with pytest.raises(CurrentPasswordInvalidError):
        await AuthService(session).change_password(
            principal=AuthenticatedPrincipal(user_id="user-1", email="user@example.com"),
            payload=PasswordChangeRequest(
                current_password="wrong-password",
                new_password="new-password",
            ),
        )

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()
