import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.accounts.models import AccountMemberRoleUpdateRequest
from app.modules.accounts.service import AccountService

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-4e-internal-auth-secret-32-characters"
USERS = ["user-owner", "user-admin", "user-editor", "user-viewer", "user-foreign"]
ACCOUNTS = ["account-a-active", "account-b-active", "account-a-archived"]
MEMBERS = [
    "owner-member",
    "admin-member",
    "editor-member",
    "viewer-member",
    "foreign-member",
    "archived-owner-member",
]

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


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
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(delete(AccountMemberModel).where(AccountMemberModel.id.in_(MEMBERS)))
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNTS)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USERS)))
        for user_id in USERS:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash="must-not-leak" if user_id == "user-admin" else None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for account_id, archived in [
            ("account-a-active", False),
            ("account-b-active", False),
            ("account-a-archived", True),
        ]:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=archived,
                    archived_at=now if archived else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        memberships = [
            ("owner-member", "user-owner", "account-a-active", AccountMemberRole.owner),
            ("admin-member", "user-admin", "account-a-active", AccountMemberRole.admin),
            ("editor-member", "user-editor", "account-a-active", AccountMemberRole.editor),
            ("viewer-member", "user-viewer", "account-a-active", AccountMemberRole.viewer),
            ("foreign-member", "user-foreign", "account-b-active", AccountMemberRole.owner),
            (
                "archived-owner-member",
                "user-owner",
                "account-a-archived",
                AccountMemberRole.owner,
            ),
        ]
        for index, (member_id, user_id, account_id, role) in enumerate(memberships):
            timestamp = now + timedelta(milliseconds=index)
            session.add(
                AccountMemberModel(
                    id=member_id,
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        await session.commit()
    await engine.dispose()


async def _member(member_id: str) -> AccountMemberModel | None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        membership = await session.get(AccountMemberModel, member_id)
        if membership is not None:
            session.expunge(membership)
    await engine.dispose()
    return membership


async def _counts() -> tuple[int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        users = await session.scalar(
            select(func.count()).select_from(UserModel).where(UserModel.id.in_(USERS))
        )
        accounts = await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id.in_(ACCOUNTS))
        )
        members = await session.scalar(
            select(func.count())
            .select_from(AccountMemberModel)
            .where(AccountMemberModel.account_id == "account-a-active")
        )
    await engine.dispose()
    return int(users or 0), int(accounts or 0), int(members or 0)


async def _verify_rollback(member_id: str, *, remove: bool) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountService(session)
        principal = AuthenticatedPrincipal(
            user_id="user-owner",
            email="user-owner@example.com",
            name="user-owner",
        )
        with (
            patch.object(
                session,
                "commit",
                AsyncMock(side_effect=RuntimeError("controlled commit failure")),
            ),
            pytest.raises(RuntimeError, match="controlled commit failure"),
        ):
            if remove:
                await service.remove_member(
                    principal=principal,
                    account_id="account-a-active",
                    member_id=member_id,
                )
            else:
                await service.update_member_role(
                    principal=principal,
                    account_id="account-a-active",
                    member_id=member_id,
                    payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.viewer),
                )
    await engine.dispose()


def test_membership_administration_against_postgresql() -> None:
    _run(_seed())
    _run(_verify_rollback("admin-member", remove=False))
    admin_after_rollback = _run(_member("admin-member"))
    assert admin_after_rollback is not None
    assert admin_after_rollback.role is AccountMemberRole.admin
    _run(_verify_rollback("editor-member", remove=True))
    assert _run(_member("editor-member")) is not None

    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret=SECRET,
            _env_file=None,
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/accounts/account-a-active/members", headers=_headers("user-owner")
        )
        assert response.status_code == 200
        members = response.json()
        assert [member["id"] for member in members] == [
            "owner-member",
            "admin-member",
            "editor-member",
            "viewer-member",
        ]
        assert members[1]["email"] == "user-admin@example.com"
        assert members[1]["name"] == "user-admin"
        assert "password_hash" not in members[1]
        assert "passwordHash" not in members[1]

        for user_id in ["user-admin", "user-editor", "user-viewer"]:
            denied = client.get(
                "/api/v1/accounts/account-a-active/members", headers=_headers(user_id)
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "account_access_denied"

        before = _run(_member("viewer-member"))
        assert before is not None
        for role in ["editor", "admin", "viewer"]:
            updated = client.patch(
                "/api/v1/accounts/account-a-active/members/viewer-member",
                headers=_headers("user-owner"),
                json={"role": role},
            )
            assert updated.status_code == 200
            assert updated.json()["role"] == role
        after = _run(_member("viewer-member"))
        assert after is not None
        assert after.id == before.id
        assert after.user_id == before.user_id
        assert after.account_id == before.account_id
        assert after.relation_type == before.relation_type
        assert after.accepted_at == before.accepted_at
        assert after.created_at == before.created_at
        assert after.updated_at > before.updated_at
        for member_id, role in [("editor-member", "viewer"), ("admin-member", "editor")]:
            changed = client.patch(
                f"/api/v1/accounts/account-a-active/members/{member_id}",
                headers=_headers("user-owner"),
                json={"role": role},
            )
            assert changed.status_code == 200
            assert changed.json()["role"] == role

        owner_change = client.patch(
            "/api/v1/accounts/account-a-active/members/owner-member",
            headers=_headers("user-owner"),
            json={"role": "admin"},
        )
        assert owner_change.status_code == 409
        assert owner_change.json()["error"]["code"] == "account_owner_immutable"
        owner_assignment = client.patch(
            "/api/v1/accounts/account-a-active/members/admin-member",
            headers=_headers("user-owner"),
            json={"role": "owner"},
        )
        assert owner_assignment.status_code == 422

        for method in ["patch", "delete"]:
            cross = client.request(
                method,
                "/api/v1/accounts/account-a-active/members/foreign-member",
                headers=_headers("user-owner"),
                json={"role": "viewer"} if method == "patch" else None,
            )
            assert cross.status_code == 404
            assert cross.json()["error"]["code"] == "account_member_not_found"
        assert _run(_member("foreign-member")) is not None

        removed = client.delete(
            "/api/v1/accounts/account-a-active/members/viewer-member",
            headers=_headers("user-owner"),
        )
        assert removed.status_code == 204
        assert removed.content == b""
        assert _run(_member("viewer-member")) is None
        assert _run(_counts()) == (5, 3, 3)

        owner_remove = client.delete(
            "/api/v1/accounts/account-a-active/members/owner-member",
            headers=_headers("user-owner"),
        )
        assert owner_remove.status_code == 409
        assert _run(_member("owner-member")) is not None

        hidden = []
        for account_id in ["missing-account", "account-b-active", "account-a-archived"]:
            hidden.extend(
                [
                    client.get(
                        f"/api/v1/accounts/{account_id}/members",
                        headers=_headers("user-owner"),
                    ),
                    client.patch(
                        f"/api/v1/accounts/{account_id}/members/admin-member",
                        headers=_headers("user-owner"),
                        json={"role": "viewer"},
                    ),
                    client.delete(
                        f"/api/v1/accounts/{account_id}/members/admin-member",
                        headers=_headers("user-owner"),
                    ),
                ]
            )
        assert all(item.status_code == 404 for item in hidden)
        assert {item.json()["error"]["code"] for item in hidden} == {"account_not_found"}
