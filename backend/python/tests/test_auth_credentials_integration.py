import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.dependencies import INTERNAL_AUTH_SERVICE_SUBJECT
from app.config.settings import Settings
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r11c-internal-auth-secret-at-least-32-characters"
LEGACY_USER_ID = "r11c-legacy-user"
REGISTERED_EMAIL = "r11c-registered@example.test"
LEGACY_EMAIL = "r11c-legacy@example.test"
LEGACY_BCRYPTJS_HASH = "$2b$12$J8Ufcs38lSf/xbQcSXw8ouVpLX3WKTJsUDRBQTMjgpN2Lrx1Sh0.."
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(subject: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": subject,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(subject)}"}


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(UserModel).where(
                (UserModel.id == LEGACY_USER_ID) | (UserModel.email == REGISTERED_EMAIL)
            )
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            UserModel(
                id=LEGACY_USER_ID,
                email=LEGACY_EMAIL,
                name="Legacy User",
                password_hash=LEGACY_BCRYPTJS_HASH,
                base_currency="CZK",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _load_user(email: str) -> UserModel | None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        user = await session.scalar(select(UserModel).where(UserModel.email == email))
        if user is not None:
            session.expunge(user)
    await engine.dispose()
    return user


def test_authentication_credentials_against_postgresql() -> None:
    _run(_seed())
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        _env_file=None,
    )

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        service_headers = _headers(INTERNAL_AUTH_SERVICE_SUBJECT)

        wrong_boundary = client.post(
            "/api/v1/auth/register",
            headers=_headers(LEGACY_USER_ID),
            json={"email": REGISTERED_EMAIL, "password": "registered-password"},
        )
        assert wrong_boundary.status_code == 401
        assert wrong_boundary.json()["error"]["code"] == "invalid_session_token"

        verified = client.post(
            "/api/v1/auth/credentials/verify",
            headers=service_headers,
            json={"email": " R11C-LEGACY@EXAMPLE.TEST ", "password": "legacy-password"},
        )
        assert verified.status_code == 200
        assert verified.json() == {
            "id": LEGACY_USER_ID,
            "email": LEGACY_EMAIL,
            "name": "Legacy User",
        }
        assert "password" not in json.dumps(verified.json()).lower()

        for email, password in [
            (LEGACY_EMAIL, "wrong-password"),
            ("r11c-missing@example.test", "wrong-password"),
        ]:
            invalid = client.post(
                "/api/v1/auth/credentials/verify",
                headers=service_headers,
                json={"email": email, "password": password},
            )
            assert invalid.status_code == 401
            assert invalid.json()["error"]["code"] == "invalid_credentials"

        registered = client.post(
            "/api/v1/auth/register",
            headers=service_headers,
            json={
                "email": " R11C-REGISTERED@EXAMPLE.TEST ",
                "password": "registered-password",
                "name": "  Registered User  ",
            },
        )
        assert registered.status_code == 201
        assert registered.json()["email"] == REGISTERED_EMAIL
        assert registered.json()["name"] == "Registered User"
        assert "password" not in json.dumps(registered.json()).lower()

        duplicate = client.post(
            "/api/v1/auth/register",
            headers=service_headers,
            json={"email": REGISTERED_EMAIL.upper(), "password": "registered-password"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "email_already_registered"

        changed = client.put(
            "/api/v1/auth/password",
            headers=_headers(LEGACY_USER_ID),
            json={
                "current_password": "legacy-password",
                "new_password": "replacement-password",
            },
        )
        assert changed.status_code == 200
        assert changed.json() == {"ok": True}

        old_password = client.post(
            "/api/v1/auth/credentials/verify",
            headers=service_headers,
            json={"email": LEGACY_EMAIL, "password": "legacy-password"},
        )
        assert old_password.status_code == 401
        new_password = client.post(
            "/api/v1/auth/credentials/verify",
            headers=service_headers,
            json={"email": LEGACY_EMAIL, "password": "replacement-password"},
        )
        assert new_password.status_code == 200

    registered_user = _run(_load_user(REGISTERED_EMAIL))
    assert registered_user is not None
    assert registered_user.password_hash is not None
    assert bcrypt.checkpw(b"registered-password", registered_user.password_hash.encode("ascii"))
    assert registered_user.base_currency == "CZK"
