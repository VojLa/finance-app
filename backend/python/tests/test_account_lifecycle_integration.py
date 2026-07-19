import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-4d-internal-auth-secret-32-characters"
USERS = ["user-owner", "user-admin", "user-editor", "user-viewer", "user-foreign"]
ACCOUNTS = [
    "active-owner",
    "active-admin",
    "active-editor",
    "active-viewer",
    "active-conflict",
    "archived-owner",
    "archived-admin",
    "archived-editor",
    "archived-viewer",
    "foreign-active",
    "foreign-archived",
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
        await session.execute(delete(HoldingModel).where(HoldingModel.account_id.in_(ACCOUNTS)))
        await session.execute(
            delete(TransactionModel).where(TransactionModel.account_id.in_(ACCOUNTS))
        )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNTS))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNTS)))
        await session.execute(delete(AssetListingModel).where(AssetListingModel.id == "listing-4d"))
        await session.execute(delete(AssetModel).where(AssetModel.id == "asset-4d"))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USERS)))

        for user_id in USERS:
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

        account_states = {
            "active-owner": False,
            "active-admin": False,
            "active-editor": False,
            "active-viewer": False,
            "active-conflict": False,
            "archived-owner": True,
            "archived-admin": True,
            "archived-editor": True,
            "archived-viewer": True,
            "foreign-active": False,
            "foreign-archived": True,
        }
        for account_id, archived in account_states.items():
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
            ("active-owner", "user-owner", AccountMemberRole.owner),
            ("active-admin", "user-admin", AccountMemberRole.admin),
            ("active-editor", "user-editor", AccountMemberRole.editor),
            ("active-viewer", "user-viewer", AccountMemberRole.viewer),
            ("active-conflict", "user-owner", AccountMemberRole.owner),
            ("archived-owner", "user-owner", AccountMemberRole.owner),
            ("archived-admin", "user-admin", AccountMemberRole.admin),
            ("archived-editor", "user-editor", AccountMemberRole.editor),
            ("archived-viewer", "user-viewer", AccountMemberRole.viewer),
            ("foreign-active", "user-foreign", AccountMemberRole.owner),
            ("foreign-archived", "user-foreign", AccountMemberRole.owner),
        ]
        for account_id, user_id, role in memberships:
            session.add(
                AccountMemberModel(
                    id=f"member-{account_id}",
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

        session.add(
            AssetModel(
                id="asset-4d",
                symbol="AUDIT",
                isin=None,
                name="Audit asset",
                asset_type=AssetType.stock,
                currency="CZK",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id="listing-4d",
                asset_id="asset-4d",
                symbol="AUDIT",
                exchange="AUDIT",
                mic=None,
                currency="CZK",
                country=None,
                provider=None,
                provider_symbol=None,
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            HoldingModel(
                id="holding-4d",
                symbol="AUDIT",
                name="Audit holding",
                asset_type=AssetType.stock,
                quantity=Decimal("1"),
                avg_buy_price=Decimal("100"),
                currency="CZK",
                current_price=Decimal("100"),
                current_value=Decimal("100"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                asset_id="asset-4d",
                listing_id="listing-4d",
                account_id="active-owner",
                calculated_at=now,
                updated_at=now,
            )
        )
        session.add(
            TransactionModel(
                id="transaction-4d",
                date=now,
                booking_date=None,
                amount=Decimal("100"),
                currency="CZK",
                reporting_amount=None,
                reporting_currency=None,
                type=TransactionType.income,
                classification=None,
                description="Audit transaction",
                note=None,
                counterparty=None,
                external_id=None,
                is_reviewed=False,
                archived_at=None,
                deleted_at=None,
                category_id=None,
                account_id="active-owner",
                import_batch_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _state(account_id: str) -> tuple[bool, datetime | None, datetime, int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        account = await session.get(AccountModel, account_id)
        assert account is not None
        members = await session.scalar(
            select(func.count())
            .select_from(AccountMemberModel)
            .where(AccountMemberModel.account_id == account_id)
        )
        holdings = await session.scalar(
            select(func.count())
            .select_from(HoldingModel)
            .where(HoldingModel.account_id == account_id)
        )
        transactions = await session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.account_id == account_id)
        )
        result = (
            account.is_archived,
            account.archived_at,
            account.updated_at,
            int(members or 0),
            int(holdings or 0),
            int(transactions or 0),
        )
    await engine.dispose()
    return result


def test_account_lifecycle_against_postgresql() -> None:
    _run(_seed())
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
        archived = client.post(
            "/api/v1/accounts/active-owner/archive", headers=_headers("user-owner")
        )
        assert archived.status_code == 200
        assert archived.json()["is_archived"] is True
        state = _run(_state("active-owner"))
        assert state[0] is True
        assert state[1] is not None and state[1] == state[2]
        assert state[3:] == (1, 1, 1)
        listed = client.get("/api/v1/accounts", headers=_headers("user-owner"))
        assert "active-owner" not in {account["id"] for account in listed.json()}
        portfolio = client.get("/api/v1/portfolio", headers=_headers("user-owner"))
        assert portfolio.status_code == 200
        assert "active-owner" not in portfolio.text
        update = client.patch(
            "/api/v1/accounts/active-owner",
            headers=_headers("user-owner"),
            json={"name": "must not update"},
        )
        assert update.status_code == 404

        restored = client.post(
            "/api/v1/accounts/archived-owner/restore", headers=_headers("user-owner")
        )
        assert restored.status_code == 200
        assert restored.json()["is_archived"] is False
        restored_state = _run(_state("archived-owner"))
        assert restored_state[0] is False and restored_state[1] is None
        listed = client.get("/api/v1/accounts", headers=_headers("user-owner"))
        assert "archived-owner" in {account["id"] for account in listed.json()}

        role_cases = [
            ("active-admin", "archive", "user-admin", 200),
            ("active-editor", "archive", "user-editor", 403),
            ("active-viewer", "archive", "user-viewer", 403),
            ("archived-admin", "restore", "user-admin", 200),
            ("archived-editor", "restore", "user-editor", 403),
            ("archived-viewer", "restore", "user-viewer", 403),
        ]
        for account_id, operation, user_id, expected_status in role_cases:
            response = client.post(
                f"/api/v1/accounts/{account_id}/{operation}", headers=_headers(user_id)
            )
            assert response.status_code == expected_status

        conflict = client.post(
            "/api/v1/accounts/active-conflict/restore", headers=_headers("user-owner")
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "account_not_archived"
        assert _run(_state("active-conflict"))[:2] == (False, None)

        hidden = [
            client.post(
                f"/api/v1/accounts/{account_id}/{operation}", headers=_headers("user-owner")
            )
            for account_id, operation in [
                ("missing-account", "archive"),
                ("foreign-active", "archive"),
                ("foreign-archived", "archive"),
                ("archived-editor", "archive"),
                ("missing-account", "restore"),
                ("foreign-active", "restore"),
                ("foreign-archived", "restore"),
            ]
        ]
        assert all(response.status_code == 404 for response in hidden)
        assert {response.json()["error"]["code"] for response in hidden} == {"account_not_found"}

    assert _run(_state("active-editor"))[0] is False
    assert _run(_state("active-viewer"))[0] is False
    assert _run(_state("archived-editor"))[0] is True
    assert _run(_state("archived-viewer"))[0] is True
    assert _run(_state("foreign-active"))[0] is False
    assert _run(_state("foreign-archived"))[0] is True
