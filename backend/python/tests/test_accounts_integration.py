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
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.accounts.models import AccountCreateRequest
from app.modules.accounts.service import AccountService

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-4c-internal-auth-secret-32-characters"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(user_id: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        now = datetime.now(UTC).replace(tzinfo=None)
        users = [
            "user-owner",
            "user-admin",
            "user-editor",
            "user-viewer",
            "user-foreign",
            "user-empty",
        ]
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.user_id.in_(users))
        )
        await session.execute(
            delete(AccountModel).where(
                or_(
                    AccountModel.id.in_(["account-shared", "account-foreign", "account-archived"]),
                    AccountModel.name == "Created account",
                )
            )
        )
        await session.execute(delete(UserModel).where(UserModel.id.in_(users)))
        for user_id in users:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for account_id, name, archived in [
            ("account-shared", "Shared", False),
            ("account-foreign", "Foreign", False),
            ("account-archived", "Archived", True),
        ]:
            session.add(
                AccountModel(
                    id=account_id,
                    name=name,
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=archived,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        memberships = [
            ("member-owner", "account-shared", "user-owner", AccountMemberRole.owner),
            ("member-admin", "account-shared", "user-admin", AccountMemberRole.admin),
            ("member-editor", "account-shared", "user-editor", AccountMemberRole.editor),
            ("member-viewer", "account-shared", "user-viewer", AccountMemberRole.viewer),
            ("member-foreign", "account-foreign", "user-foreign", AccountMemberRole.owner),
            ("member-archived", "account-archived", "user-owner", AccountMemberRole.owner),
        ]
        for member_id, account_id, user_id, role in memberships:
            session.add(
                AccountMemberModel(
                    id=member_id,
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()


async def _count_account(account_id: str) -> int:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        count = await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id == account_id)
        )
    await engine.dispose()
    return int(count or 0)


async def _verify_atomic_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    failed_id = UUID("00000000-0000-4000-8000-000000000001")
    member_id = UUID("00000000-0000-4000-8000-000000000002")
    ids = iter([failed_id, member_id])
    monkeypatch.setattr("app.modules.accounts.service.uuid4", lambda: next(ids))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountService(session)
        with pytest.raises(IntegrityError):
            await service.create_account(
                principal=AuthenticatedPrincipal(
                    user_id="missing-user",
                    email="missing@example.com",
                    name=None,
                ),
                payload=AccountCreateRequest(name="Must roll back", type="bank", currency="CZK"),
            )
        count = await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id == str(failed_id))
        )
        assert count == 0
    await engine.dispose()


def test_accounts_api_against_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        owner = client.get("/api/v1/accounts", headers=_headers("user-owner"))
        assert owner.status_code == 200
        assert [account["id"] for account in owner.json()] == ["account-shared"]
        assert owner.json()[0]["role"] == "owner"
        assert owner.json()[0]["relation_type"] == "owner"

        foreign = client.get("/api/v1/accounts", headers=_headers("user-foreign"))
        assert [account["id"] for account in foreign.json()] == ["account-foreign"]
        assert client.get("/api/v1/accounts", headers=_headers("user-empty")).json() == []
        overridden = client.get(
            "/api/v1/accounts?user_id=user-foreign",
            headers=_headers("user-owner"),
        )
        assert [account["id"] for account in overridden.json()] == ["account-shared"]

        created = client.post(
            "/api/v1/accounts",
            headers=_headers("user-owner"),
            json={"name": "  Created account  ", "type": "cash", "currency": "eur"},
        )
        assert created.status_code == 201
        assert created.json()["name"] == "Created account"
        assert created.json()["currency"] == "EUR"
        assert created.json()["role"] == "owner"
        assert created.json()["relation_type"] == "owner"
        assert _run(_count_account(created.json()["id"])) == 1

        for user_id in ["user-owner", "user-admin", "user-editor"]:
            updated = client.patch(
                "/api/v1/accounts/account-shared",
                headers=_headers(user_id),
                json={"name": f"Updated by {user_id}", "currency": "usd"},
            )
            assert updated.status_code == 200
            assert updated.json()["currency"] == "USD"

        viewer = client.patch(
            "/api/v1/accounts/account-shared",
            headers=_headers("user-viewer"),
            json={"name": "Viewer write"},
        )
        assert viewer.status_code == 403
        assert viewer.json()["error"]["code"] == "account_access_denied"

        hidden_responses = [
            client.patch(
                f"/api/v1/accounts/{account_id}",
                headers=_headers("user-owner"),
                json={"name": "Unauthorized write"},
            )
            for account_id in ["account-foreign", "account-archived", "missing-account"]
        ]
        assert [response.status_code for response in hidden_responses] == [404, 404, 404]
        assert [response.json()["error"]["code"] for response in hidden_responses] == [
            "account_not_found",
            "account_not_found",
            "account_not_found",
        ]
        assert client.get("/api/v1/health/live").status_code == 200

    _run(_verify_atomic_rollback(monkeypatch))
