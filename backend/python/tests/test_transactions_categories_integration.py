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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.categories import CategoryModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    CategoryType,
)
from app.db.models.transactions import TransactionModel, TransactionPairModel, TransactionSplitModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r11e-internal-auth-secret-32-characters"
USER_IDS = ("r11e-owner", "r11e-viewer", "r11e-foreign")
ACCOUNT_IDS = ("r11e-account", "r11e-foreign-account")
STATIC_CATEGORY_IDS = ("r11e-default", "r11e-owned", "r11e-foreign-category")

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


async def _cleanup(session: AsyncSession) -> None:
    transaction_ids = select(TransactionModel.id).where(
        TransactionModel.account_id.in_(ACCOUNT_IDS)
    )
    await session.execute(
        delete(TransactionPairModel).where(
            (TransactionPairModel.from_transaction_id.in_(transaction_ids))
            | (TransactionPairModel.to_transaction_id.in_(transaction_ids))
        )
    )
    await session.execute(
        delete(TransactionSplitModel).where(
            TransactionSplitModel.transaction_id.in_(transaction_ids)
        )
    )
    await session.execute(
        delete(TransactionModel).where(TransactionModel.account_id.in_(ACCOUNT_IDS))
    )
    await session.execute(
        delete(AccountCanonicalChangeModel).where(
            AccountCanonicalChangeModel.account_id.in_(ACCOUNT_IDS)
        )
    )
    await session.execute(
        delete(AccountCanonicalStateModel).where(
            AccountCanonicalStateModel.account_id.in_(ACCOUNT_IDS)
        )
    )
    await session.execute(
        delete(CategoryModel).where(
            (CategoryModel.id.in_(STATIC_CATEGORY_IDS)) | (CategoryModel.user_id.in_(USER_IDS))
        )
    )
    await session.execute(
        delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNT_IDS))
    )
    await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNT_IDS)))
    await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await _cleanup(session)
        for user_id in USER_IDS:
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
        for account_id in ACCOUNT_IDS:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        memberships = (
            ("r11e-owner-member", "r11e-account", "r11e-owner", AccountMemberRole.owner),
            ("r11e-viewer-member", "r11e-account", "r11e-viewer", AccountMemberRole.viewer),
            (
                "r11e-foreign-member",
                "r11e-foreign-account",
                "r11e-foreign",
                AccountMemberRole.owner,
            ),
        )
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
        categories = (
            ("r11e-default", "Default", CategoryType.expense, True, None),
            ("r11e-owned", "Owned", CategoryType.expense, False, "r11e-owner"),
            (
                "r11e-foreign-category",
                "Foreign",
                CategoryType.expense,
                False,
                "r11e-foreign",
            ),
        )
        for category_id, name, category_type, is_default, user_id in categories:
            session.add(
                CategoryModel(
                    id=category_id,
                    name=name,
                    icon=None,
                    color=None,
                    type=category_type,
                    parent_id=None,
                    is_default=is_default,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()


async def _audit() -> tuple[int, int, list[tuple[str, Any, Any]]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        state = await session.get(AccountCanonicalStateModel, "r11e-account")
        assert state is not None
        changes = list(
            (
                await session.execute(
                    select(
                        AccountCanonicalChangeModel.entity_id,
                        AccountCanonicalChangeModel.revision,
                        AccountCanonicalChangeModel.kind,
                    )
                    .where(AccountCanonicalChangeModel.account_id == "r11e-account")
                    .order_by(AccountCanonicalChangeModel.revision)
                )
            ).all()
        )
        active = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(TransactionModel)
                    .where(
                        TransactionModel.account_id == "r11e-account",
                        TransactionModel.deleted_at.is_(None),
                    )
                )
            )
            or 0
        )
        result = (state.last_revision, active, changes)
    await engine.dispose()
    return result


def test_transaction_and_category_http_contract_on_postgresql() -> None:
    _run(_seed())
    assert DATABASE_URL is not None
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
        categories = client.get("/api/v1/categories", headers=_headers("r11e-owner"))
        assert categories.status_code == 200
        assert {item["id"] for item in categories.json()} == {"r11e-default", "r11e-owned"}

        create_category_payload = {
            "name": "Child",
            "type": "expense",
            "parentId": "r11e-owned",
            "idempotencyKey": "create-child",
        }
        category = client.post(
            "/api/v1/categories",
            headers=_headers("r11e-owner"),
            json=create_category_payload,
        )
        assert category.status_code == 201
        category_id = category.json()["id"]
        replay = client.post(
            "/api/v1/categories",
            headers=_headers("r11e-owner"),
            json=create_category_payload,
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == category_id
        changed_replay = client.post(
            "/api/v1/categories",
            headers=_headers("r11e-owner"),
            json={**create_category_payload, "name": "Different"},
        )
        assert changed_replay.status_code == 409
        assert (
            client.patch(
                "/api/v1/categories/r11e-default",
                headers=_headers("r11e-owner"),
                json={"name": "No"},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/v1/categories/r11e-owned",
                headers=_headers("r11e-owner"),
                json={"parentId": category_id},
            ).status_code
            == 409
        )

        transaction_payload = {
            "date": "2026-08-09",
            "amount": "123.456789",
            "currency": "CZK",
            "type": "expense",
            "accountId": "r11e-account",
            "description": "Exact grocery",
            "categoryId": category_id,
            "idempotencyKey": "create-transaction",
        }
        transaction = client.post(
            "/api/v1/transactions",
            headers=_headers("r11e-owner"),
            json=transaction_payload,
        )
        assert transaction.status_code == 201
        assert transaction.json()["amount"] == "-123.456789"
        transaction_id = transaction.json()["id"]
        replay = client.post(
            "/api/v1/transactions",
            headers=_headers("r11e-owner"),
            json=transaction_payload,
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == transaction_id
        assert (
            client.post(
                "/api/v1/transactions",
                headers=_headers("r11e-owner"),
                json={**transaction_payload, "amount": "1.000001"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/transactions",
                headers=_headers("r11e-viewer"),
                json={**transaction_payload, "idempotencyKey": "viewer-write"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/transactions",
                headers=_headers("r11e-owner"),
                json={
                    **transaction_payload,
                    "categoryId": "r11e-foreign-category",
                    "idempotencyKey": "foreign-category",
                },
            ).status_code
            == 422
        )

        listing = client.get(
            "/api/v1/transactions?page=1&type=expense&q=grocery",
            headers=_headers("r11e-owner"),
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["transactions"][0]["id"] == transaction_id
        assert (
            client.get("/api/v1/transactions?page=1", headers=_headers("r11e-foreign")).json()[
                "total"
            ]
            == 0
        )

        update_payload = {"amount": "99.000001", "idempotencyKey": "update-transaction"}
        updated = client.patch(
            f"/api/v1/transactions/{transaction_id}",
            headers=_headers("r11e-owner"),
            json=update_payload,
        )
        assert updated.status_code == 200
        assert updated.json()["amount"] == "-99.000001"
        replacement_id = updated.json()["id"]
        assert replacement_id != transaction_id
        replay = client.patch(
            f"/api/v1/transactions/{transaction_id}",
            headers=_headers("r11e-owner"),
            json=update_payload,
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == replacement_id
        assert (
            client.patch(
                f"/api/v1/transactions/{transaction_id}",
                headers=_headers("r11e-owner"),
                json={"amount": "98", "idempotencyKey": "update-transaction"},
            ).status_code
            == 409
        )

        delete_payload = {"idempotencyKey": "delete-transaction"}
        deleted = client.request(
            "DELETE",
            f"/api/v1/transactions/{replacement_id}",
            headers=_headers("r11e-owner"),
            json=delete_payload,
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        assert (
            client.request(
                "DELETE",
                f"/api/v1/transactions/{replacement_id}",
                headers=_headers("r11e-owner"),
                json=delete_payload,
            ).status_code
            == 200
        )

        category_effect_transaction = client.post(
            "/api/v1/transactions",
            headers=_headers("r11e-owner"),
            json={
                **transaction_payload,
                "description": "Category delete effect",
                "idempotencyKey": "category-effect",
            },
        )
        assert category_effect_transaction.status_code == 201
        assert (
            client.delete(
                f"/api/v1/categories/{category_id}", headers=_headers("r11e-owner")
            ).status_code
            == 200
        )
        listing = client.get("/api/v1/transactions?page=1", headers=_headers("r11e-owner"))
        assert listing.status_code == 200
        effect_row = next(
            row
            for row in listing.json()["transactions"]
            if row["description"] == "Category delete effect"
        )
        assert effect_row["categoryId"] is None

    last_revision, active, changes = _run(_audit())
    assert last_revision == 4
    assert active == 1
    assert [revision for _, revision, _ in changes] == [1, 2, 3, 4]
    assert all(kind == "transaction" for _, _, kind in changes)
