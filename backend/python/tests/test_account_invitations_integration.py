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
from app.db.models.accounts import AccountInviteModel, AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountInviteStatus,
    AccountMemberRole,
    AccountRelationType,
    AccountType,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.accounts.invitations import (
    AccountInvitationService,
    AccountInviteAcceptRequest,
    AccountInviteConflictError,
    AccountInviteCreateRequest,
)

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-4f-internal-auth-secret-32-characters"
USERS = [
    "user-owner",
    "user-admin",
    "user-editor",
    "user-viewer",
    "user-invitee",
    "user-wrong-email",
    "user-existing-member",
]
ACCOUNTS = ["account-active", "account-archived", "account-foreign"]

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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(delete(AccountInviteModel))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNTS))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNTS)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USERS)))
        for user_id in USERS:
            email = "invitee@example.com" if user_id == "user-invitee" else f"{user_id}@example.com"
            session.add(
                UserModel(
                    id=user_id,
                    email=email,
                    name=user_id,
                    password_hash="must-not-leak" if user_id == "user-admin" else None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for account_id, archived in [
            ("account-active", False),
            ("account-archived", True),
            ("account-foreign", False),
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
            ("member-owner", "user-owner", "account-active", AccountMemberRole.owner),
            ("member-admin", "user-admin", "account-active", AccountMemberRole.admin),
            ("member-editor", "user-editor", "account-active", AccountMemberRole.editor),
            ("member-viewer", "user-viewer", "account-active", AccountMemberRole.viewer),
            (
                "member-existing",
                "user-existing-member",
                "account-active",
                AccountMemberRole.viewer,
            ),
            ("member-archived", "user-owner", "account-archived", AccountMemberRole.owner),
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


async def _insert_invite(
    invite_id: str,
    token: str,
    email: str,
    *,
    account_id: str = "account-active",
    status: AccountInviteStatus = AccountInviteStatus.pending,
    expires_delta: timedelta = timedelta(hours=24),
) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        session.add(
            AccountInviteModel(
                id=invite_id,
                account_id=account_id,
                inviter_id="user-owner",
                accepted_by_id="user-invitee" if status is AccountInviteStatus.accepted else None,
                email=email,
                role=AccountMemberRole.editor,
                status=status,
                token_hash=_hash(token),
                expires_at=now + expires_delta,
                accepted_at=now if status is AccountInviteStatus.accepted else None,
                revoked_at=now if status is AccountInviteStatus.revoked else None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _invite(invite_id: str) -> AccountInviteModel | None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        value = await session.get(AccountInviteModel, invite_id)
        if value is not None:
            session.expunge(value)
    await engine.dispose()
    return value


async def _membership_count(user_id: str) -> int:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AccountMemberModel)
            .where(
                AccountMemberModel.account_id == "account-active",
                AccountMemberModel.user_id == user_id,
            )
        )
    await engine.dispose()
    return int(count or 0)


async def _verify_rollbacks() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="user-owner", email="user-owner@example.com", name="Owner"
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountInvitationService(session)
        rollback = AsyncMock(wraps=session.rollback)
        with (
            patch.object(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed"))),
            patch.object(session, "rollback", rollback),
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            await service.create_invite(
                principal=principal,
                account_id="account-active",
                payload=AccountInviteCreateRequest(email="rollback-create@example.com"),
            )
        rollback.assert_awaited_once()
    assert await _find_invite_email("rollback-create@example.com") is None

    await _insert_invite("invite-rollback-revoke", "r" * 43, "revoke@example.com")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountInvitationService(session)
        with (
            patch.object(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed"))),
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            await service.revoke_invite(
                principal=principal,
                account_id="account-active",
                invite_id="invite-rollback-revoke",
            )
    revoke_after_rollback = await _invite("invite-rollback-revoke")
    assert revoke_after_rollback is not None
    assert revoke_after_rollback.status is AccountInviteStatus.pending

    await _insert_invite(
        "invite-rollback-accept",
        "a" * 43,
        "user-wrong-email@example.com",
    )
    invitee = AuthenticatedPrincipal(
        user_id="user-wrong-email",
        email="user-wrong-email@example.com",
        name="Rollback invitee",
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountInvitationService(session)
        with (
            patch.object(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed"))),
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            await service.accept_invite(
                principal=invitee,
                payload=AccountInviteAcceptRequest(token="a" * 43),
            )
    accept_after_rollback = await _invite("invite-rollback-accept")
    assert accept_after_rollback is not None
    assert accept_after_rollback.status is AccountInviteStatus.pending
    assert await _membership_count("user-wrong-email") == 0
    await engine.dispose()


async def _find_invite_email(email: str) -> AccountInviteModel | None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        value = await session.scalar(
            select(AccountInviteModel).where(AccountInviteModel.email == email)
        )
        if value is not None:
            session.expunge(value)
    await engine.dispose()
    return value


def test_invitation_workflow_against_postgresql() -> None:
    _run(_seed())
    _run(_verify_rollbacks())
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
        _run(
            _insert_invite(
                "invite-old-expired",
                "o" * 43,
                "invitee@example.com",
                expires_delta=timedelta(hours=-1),
            )
        )
        _run(
            _insert_invite(
                "invite-same-email-foreign",
                "d" * 43,
                "invitee@example.com",
                account_id="account-foreign",
            )
        )
        created = client.post(
            "/api/v1/accounts/account-active/invites",
            headers=_headers("user-owner"),
            json={"email": "  Invitee@Example.COM  ", "role": "editor", "expires_in_hours": 72},
        )
        assert created.status_code == 201
        created_body = created.json()
        raw_token = created_body["token"]
        persisted = _run(_invite(created_body["id"]))
        assert persisted is not None
        assert persisted.email == "invitee@example.com"
        assert persisted.inviter_id == "user-owner"
        assert persisted.status is AccountInviteStatus.pending
        assert persisted.token_hash == _hash(raw_token)
        assert persisted.token_hash != raw_token
        assert len(persisted.token_hash) == 64

        for user_id in ["user-admin", "user-editor", "user-viewer"]:
            denied = client.post(
                "/api/v1/accounts/account-active/invites",
                headers=_headers(user_id),
                json={"email": f"{user_id}-new@example.com"},
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "account_access_denied"

        duplicate = client.post(
            "/api/v1/accounts/account-active/invites",
            headers=_headers("user-owner"),
            json={"email": "INVITEE@example.com"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "account_invite_pending"

        listing = client.get(
            "/api/v1/accounts/account-active/invites", headers=_headers("user-owner")
        )
        assert listing.status_code == 200
        assert all("token" not in item and "token_hash" not in item for item in listing.json())
        assert "password_hash" not in json.dumps(listing.json())
        listed_ids = [item["id"] for item in listing.json()]
        listed_rows = [_run(_invite(invite_id)) for invite_id in listed_ids]
        assert all(row is not None for row in listed_rows)
        listed_keys = [(row.created_at, row.id) for row in listed_rows if row is not None]
        assert listed_keys == sorted(listed_keys)
        assert (
            client.get(
                "/api/v1/accounts/account-active/invites", headers=_headers("user-admin")
            ).status_code
            == 403
        )

        accepted = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-invitee"),
            json={"token": raw_token},
        )
        assert accepted.status_code == 201
        assert accepted.json()["account_id"] == "account-active"
        assert "token" not in accepted.json()
        accepted_invite = _run(_invite(created_body["id"]))
        assert accepted_invite is not None
        assert accepted_invite.status is AccountInviteStatus.accepted
        assert accepted_invite.accepted_by_id == "user-invitee"
        assert accepted_invite.accepted_at == accepted_invite.updated_at
        assert _run(_membership_count("user-invitee")) == 1

        repeated = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-invitee"),
            json={"token": raw_token},
        )
        assert repeated.status_code == 409
        assert repeated.json()["error"]["code"] == "account_invite_not_pending"
        accepted_revoke = client.delete(
            f"/api/v1/accounts/account-active/invites/{created_body['id']}",
            headers=_headers("user-owner"),
        )
        assert accepted_revoke.status_code == 409
        assert accepted_revoke.json()["error"]["code"] == "account_invite_not_pending"

        invalid_cases = [
            (
                "unknown-token-value-that-is-long-enough-000",
                "user-wrong-email",
                404,
                "account_invite_not_found",
            ),
        ]
        for token, user_id, expected_status, code in invalid_cases:
            response = client.post(
                "/api/v1/accounts/invites/accept",
                headers=_headers(user_id),
                json={"token": token},
            )
            assert response.status_code == expected_status
            assert response.json()["error"]["code"] == code

        wrong_token = "w" * 43
        _run(_insert_invite("invite-wrong", wrong_token, "invitee@example.com"))
        wrong = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-wrong-email"),
            json={"token": wrong_token},
        )
        assert wrong.status_code == 404
        assert wrong.json()["error"]["code"] == "account_invite_not_found"
        wrong_invite = _run(_invite("invite-wrong"))
        assert wrong_invite is not None
        assert wrong_invite.status is AccountInviteStatus.pending

        existing_token = "e" * 43
        _run(_insert_invite("invite-existing", existing_token, "user-existing-member@example.com"))
        existing = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-existing-member"),
            json={"token": existing_token},
        )
        assert existing.status_code == 409
        assert existing.json()["error"]["code"] == "account_membership_exists"

        expired_token = "x" * 43
        _run(
            _insert_invite(
                "invite-expired-time",
                expired_token,
                "invitee@example.com",
                expires_delta=timedelta(hours=-1),
            )
        )
        expired = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-invitee"),
            json={"token": expired_token},
        )
        assert expired.status_code == 409
        assert expired.json()["error"]["code"] == "account_invite_expired"
        expired_invite = _run(_invite("invite-expired-time"))
        assert expired_invite is not None
        assert expired_invite.status is AccountInviteStatus.expired

        archived_token = "z" * 43
        _run(
            _insert_invite(
                "invite-archived",
                archived_token,
                "invitee@example.com",
                account_id="account-archived",
            )
        )
        archived = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-invitee"),
            json={"token": archived_token},
        )
        assert archived.status_code == 404
        assert archived.json()["error"]["code"] == "account_invite_not_found"

        revoked_token = "q" * 43
        _run(
            _insert_invite(
                "invite-already-revoked",
                revoked_token,
                "invitee@example.com",
                status=AccountInviteStatus.revoked,
            )
        )
        revoked_accept = client.post(
            "/api/v1/accounts/invites/accept",
            headers=_headers("user-invitee"),
            json={"token": revoked_token},
        )
        assert revoked_accept.status_code == 409
        assert revoked_accept.json()["error"]["code"] == "account_invite_not_pending"

        revoke_token = "v" * 43
        _run(_insert_invite("invite-revoke", revoke_token, "revoke@example.com"))
        revoked = client.delete(
            "/api/v1/accounts/account-active/invites/invite-revoke",
            headers=_headers("user-owner"),
        )
        assert revoked.status_code == 204
        assert revoked.content == b""
        revoked_invite = _run(_invite("invite-revoke"))
        assert revoked_invite is not None
        assert revoked_invite.status is AccountInviteStatus.revoked
        assert revoked_invite.revoked_at == revoked_invite.updated_at
        denied_revoke = client.delete(
            "/api/v1/accounts/account-active/invites/invite-revoke",
            headers=_headers("user-admin"),
        )
        assert denied_revoke.status_code == 403
        again = client.delete(
            "/api/v1/accounts/account-active/invites/invite-revoke",
            headers=_headers("user-owner"),
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "account_invite_not_pending"

        final_listing = client.get(
            "/api/v1/accounts/account-active/invites",
            headers=_headers("user-owner"),
        )
        assert final_listing.status_code == 200
        statuses = {item["id"]: item["status"] for item in final_listing.json()}
        assert statuses[created_body["id"]] == "accepted"
        assert statuses["invite-revoke"] == "revoked"
        assert statuses["invite-expired-time"] == "expired"
        assert all(
            "token" not in item and "token_hash" not in item for item in final_listing.json()
        )

        foreign_token = "f" * 43
        _run(
            _insert_invite(
                "invite-foreign", foreign_token, "foreign@example.com", account_id="account-foreign"
            )
        )
        cross = client.delete(
            "/api/v1/accounts/account-active/invites/invite-foreign",
            headers=_headers("user-owner"),
        )
        assert cross.status_code == 404
        assert cross.json()["error"]["code"] == "account_invite_not_found"

        for account_id in ["missing-account", "account-foreign", "account-archived"]:
            hidden = client.get(
                f"/api/v1/accounts/{account_id}/invites", headers=_headers("user-owner")
            )
            assert hidden.status_code == 404
            assert hidden.json()["error"]["code"] == "account_not_found"


async def _accept_concurrently(token: str) -> list[object]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="user-invitee", email="invitee@example.com", name="Invitee"
    )

    async def accept() -> object:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await AccountInvitationService(session).accept_invite(
                principal=principal,
                payload=AccountInviteAcceptRequest(token=token),
            )

    results = await asyncio.gather(accept(), accept(), return_exceptions=True)
    await engine.dispose()
    return list(results)


def test_concurrent_invitation_acceptance_is_single_use() -> None:
    _run(_seed())
    token = "c" * 43
    _run(_insert_invite("invite-concurrent", token, "invitee@example.com"))
    results = _run(_accept_concurrently(token))

    successes = [result for result in results if not isinstance(result, BaseException)]
    conflicts = [result for result in results if isinstance(result, AccountInviteConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "account_invite_not_pending"
    assert _run(_membership_count("user-invitee")) == 1
    invite = _run(_invite("invite-concurrent"))
    assert invite is not None
    assert invite.status is AccountInviteStatus.accepted
