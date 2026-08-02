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
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.accounts.models import AccountCreateRequest
from app.modules.accounts.service import AccountService

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "version-0-1-account-cutover-secret-32-characters"
OWNER_ID = "version-0-1-r1-owner"
FOREIGN_ID = "version-0-1-r1-foreign"
USER_IDS = [OWNER_ID, FOREIGN_ID]

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
            "jti": f"r1-{user_id}-{now}",
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


async def _seed_clean_users() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        account_ids = list(
            (
                await session.scalars(
                    select(AccountMemberModel.account_id).where(
                        AccountMemberModel.user_id.in_(USER_IDS)
                    )
                )
            ).all()
        )
        if account_ids:
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))
        for user_id in USER_IDS:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name=user_id,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()


async def _remove_test_users() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        account_ids = list(
            (
                await session.scalars(
                    select(AccountMemberModel.account_id).where(
                        AccountMemberModel.user_id.in_(USER_IDS)
                    )
                )
            ).all()
        )
        if account_ids:
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))
        await session.commit()
    await engine.dispose()


async def _account_state(account_ids: list[str]) -> list[tuple[AccountModel, int]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        accounts = list(
            (
                await session.scalars(
                    select(AccountModel)
                    .where(AccountModel.id.in_(account_ids))
                    .order_by(AccountModel.created_at, AccountModel.id)
                )
            ).all()
        )
        result = []
        for account in accounts:
            membership_count = await session.scalar(
                select(func.count())
                .select_from(AccountMemberModel)
                .where(AccountMemberModel.account_id == account.id)
            )
            result.append((account, int(membership_count or 0)))
    await engine.dispose()
    return result


async def _verify_atomic_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    failed_id = UUID("10000000-0000-4000-8000-000000000001")
    member_id = UUID("10000000-0000-4000-8000-000000000002")
    identifiers = iter([failed_id, member_id])
    monkeypatch.setattr("app.modules.accounts.service.uuid4", lambda: next(identifiers))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AccountService(session)
        with pytest.raises(IntegrityError):
            await service.create_account(
                principal=AuthenticatedPrincipal(
                    user_id="version-0-1-r1-missing-user",
                    email="missing@example.test",
                    name=None,
                ),
                payload=AccountCreateRequest(
                    name="Rollback account",
                    type="bank",
                    currency="CZK",
                ),
            )
        account_count = await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id == str(failed_id))
        )
        membership_count = await session.scalar(
            select(func.count())
            .select_from(AccountMemberModel)
            .where(AccountMemberModel.id == str(member_id))
        )
        assert account_count == 0
        assert membership_count == 0
    await engine.dispose()


def test_account_cutover_contract_against_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(_seed_clean_users())
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
        assert client.get("/api/v1/accounts", headers=_headers(OWNER_ID)).json() == []
        assert app.state.database.engine.sync_engine.pool.checkedout() == 0

        created = client.post(
            "/api/v1/accounts",
            headers=_headers(OWNER_ID),
            json={
                "name": "  R1 broker  ",
                "type": "broker",
                "currency": "eur",
                "color": "#123456",
                "notes": "R1 acceptance",
            },
        )
        assert created.status_code == 201
        account_id = created.json()["id"]
        assert created.json() == {
            **created.json(),
            "name": "R1 broker",
            "type": "broker",
            "currency": "EUR",
            "role": "owner",
            "relation_type": "owner",
            "is_archived": False,
        }

        replay = client.post(
            "/api/v1/accounts",
            headers=_headers(OWNER_ID),
            json={"name": "R1 broker replay", "type": "broker", "currency": "EUR"},
        )
        assert replay.status_code == 201
        replay_id = replay.json()["id"]

        persisted = _run(_account_state([account_id, replay_id]))
        assert len(persisted) == 2
        assert all(member_count == 1 for _account, member_count in persisted)
        assert all(account.type.value == "broker" for account, _member_count in persisted)

        listed = client.get("/api/v1/accounts", headers=_headers(OWNER_ID))
        assert listed.status_code == 200
        assert {account["id"] for account in listed.json()} == {account_id, replay_id}
        assert {(account["role"], account["relation_type"]) for account in listed.json()} == {
            ("owner", "owner")
        }

        foreign = client.get("/api/v1/accounts", headers=_headers(FOREIGN_ID))
        assert foreign.status_code == 200
        assert foreign.json() == []
        hidden = client.patch(
            f"/api/v1/accounts/{account_id}",
            headers=_headers(FOREIGN_ID),
            json={"name": "Foreign write"},
        )
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "account_not_found"

        updated = client.patch(
            f"/api/v1/accounts/{account_id}",
            headers=_headers(OWNER_ID),
            json={"name": "Updated R1 broker", "currency": "usd"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Updated R1 broker"
        assert updated.json()["currency"] == "USD"
        assert updated.json()["type"] == "broker"

        archived = client.post(
            f"/api/v1/accounts/{account_id}/archive",
            headers=_headers(OWNER_ID),
        )
        assert archived.status_code == 200
        assert archived.json()["is_archived"] is True
        after_archive = client.get("/api/v1/accounts", headers=_headers(OWNER_ID))
        assert account_id not in {account["id"] for account in after_archive.json()}
        assert replay_id in {account["id"] for account in after_archive.json()}

        preserved = _run(_account_state([account_id]))
        assert len(preserved) == 1
        assert preserved[0][0].is_archived is True
        assert preserved[0][1] == 1
        assert app.state.database.engine.sync_engine.pool.checkedout() == 0

    _run(_verify_atomic_rollback(monkeypatch))
    _run(_remove_test_users())
