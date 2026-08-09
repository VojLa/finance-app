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
from app.db.models.budgets import BudgetAlertModel, BudgetModel
from app.db.models.categories import CategoryModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    CategoryType,
    TransactionClassification,
    TransactionType,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.budgets.service import month_range, previous_month

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r11f-internal-auth-secret-32-characters"
USER_IDS = ("r11f-owner", "r11f-viewer", "r11f-foreign")
ACCOUNT_IDS = ("r11f-account", "r11f-foreign-account")
CATEGORY_IDS = ("r11f-food", "r11f-foreign-category")

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
    await session.execute(
        delete(TransactionModel).where(TransactionModel.account_id.in_(ACCOUNT_IDS))
    )
    await session.execute(delete(BudgetModel).where(BudgetModel.user_id.in_(USER_IDS)))
    await session.execute(
        delete(CategoryModel).where(
            (CategoryModel.id.in_(CATEGORY_IDS)) | (CategoryModel.user_id.in_(USER_IDS))
        )
    )
    await session.execute(
        delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNT_IDS))
    )
    await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNT_IDS)))
    await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))


async def _seed() -> tuple[int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    month, year = now.month, now.year
    previous_month_value, previous_year = previous_month(month, year)
    current_start, _ = month_range(month, year)
    previous_start, _ = month_range(previous_month_value, previous_year)
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
        for member_id, account_id, user_id, role in (
            ("r11f-owner-member", "r11f-account", "r11f-owner", AccountMemberRole.owner),
            ("r11f-viewer-member", "r11f-account", "r11f-viewer", AccountMemberRole.viewer),
            (
                "r11f-foreign-member",
                "r11f-foreign-account",
                "r11f-foreign",
                AccountMemberRole.owner,
            ),
        ):
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
        for category_id, name, user_id in (
            ("r11f-food", "Food", "r11f-owner"),
            ("r11f-foreign-category", "Foreign", "r11f-foreign"),
        ):
            session.add(
                CategoryModel(
                    id=category_id,
                    name=name,
                    icon=None,
                    color="#00aa00",
                    type=CategoryType.expense,
                    parent_id=None,
                    is_default=False,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()

        transactions = (
            (
                "r11f-previous-expense",
                previous_start,
                Decimal("-200.000000"),
                "CZK",
                None,
                None,
                TransactionType.expense,
                "r11f-account",
                "r11f-food",
            ),
            (
                "r11f-current-expense",
                current_start,
                Decimal("-800.000000"),
                "CZK",
                None,
                None,
                TransactionType.expense,
                "r11f-account",
                "r11f-food",
            ),
            (
                "r11f-current-eur-expense",
                current_start,
                Decimal("-4.000000"),
                "EUR",
                Decimal("-100.000000"),
                "CZK",
                TransactionType.expense,
                "r11f-account",
                "r11f-food",
            ),
            (
                "r11f-current-income",
                current_start,
                Decimal("2000.000000"),
                "CZK",
                None,
                None,
                TransactionType.income,
                "r11f-account",
                None,
            ),
            (
                "r11f-foreign-expense",
                current_start,
                Decimal("-999.000000"),
                "CZK",
                None,
                None,
                TransactionType.expense,
                "r11f-foreign-account",
                "r11f-foreign-category",
            ),
        )
        for (
            transaction_id,
            date,
            amount,
            currency,
            reporting_amount,
            reporting_currency,
            transaction_type,
            account_id,
            category_id,
        ) in transactions:
            session.add(
                TransactionModel(
                    id=transaction_id,
                    date=date,
                    booking_date=None,
                    amount=amount,
                    currency=currency,
                    reporting_amount=reporting_amount,
                    reporting_currency=reporting_currency,
                    type=transaction_type,
                    classification=(
                        TransactionClassification.real_income
                        if transaction_type is TransactionType.income
                        else TransactionClassification.real_expense
                    ),
                    description=transaction_id,
                    note=None,
                    counterparty=None,
                    external_id=None,
                    is_reviewed=True,
                    archived_at=None,
                    deleted_at=None,
                    category_id=category_id,
                    account_id=account_id,
                    import_batch_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()
    return month, year


async def _read_counts() -> tuple[int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        values = (
            int((await session.scalar(select(func.count()).select_from(BudgetModel))) or 0),
            int((await session.scalar(select(func.count()).select_from(BudgetAlertModel))) or 0),
            int((await session.scalar(select(func.count()).select_from(TransactionModel))) or 0),
        )
    await engine.dispose()
    return values


def test_budget_and_operational_dashboard_on_postgresql() -> None:
    month, year = _run(_seed())
    previous_month_value, previous_year = previous_month(month, year)
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
        assert (
            client.get(
                f"/api/v1/budgets/monthly?month={month}&year={year}",
                headers=_headers("r11f-owner"),
            ).json()
            is None
        )
        previous = client.put(
            "/api/v1/budgets/monthly",
            headers=_headers("r11f-owner"),
            json={
                "month": previous_month_value,
                "year": previous_year,
                "rollover": False,
                "items": [{"categoryId": "r11f-food", "amount": "1000", "currency": "CZK"}],
            },
        )
        assert previous.status_code == 200
        assert previous.json()["totalSpent"] == "200.000000"

        current = client.put(
            "/api/v1/budgets/monthly",
            headers=_headers("r11f-owner"),
            json={
                "month": month,
                "year": year,
                "rollover": True,
                "items": [{"categoryId": "r11f-food", "amount": "1000", "currency": "CZK"}],
            },
        )
        assert current.status_code == 200
        body = current.json()
        assert body["accountIds"] == ["r11f-account"]
        assert body["totalBaseLimit"] == "1000.000000"
        assert body["totalRollover"] == "800.000000"
        assert body["totalLimit"] == "1800.000000"
        assert body["totalSpent"] == "900.000000"
        assert body["progressPct"] == "50.0000"
        assert body["alerts"] == []

        assert (
            client.put(
                "/api/v1/budgets/monthly",
                headers=_headers("r11f-owner"),
                json={
                    "month": month,
                    "year": year,
                    "items": [
                        {
                            "categoryId": "r11f-foreign-category",
                            "amount": "100",
                            "currency": "CZK",
                        }
                    ],
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"/api/v1/budgets/monthly?month={month}&year={year}",
                headers=_headers("r11f-foreign"),
            ).json()
            is None
        )

        before = _run(_read_counts())
        dashboard = client.get("/api/v1/operational-dashboard", headers=_headers("r11f-owner"))
        after = _run(_read_counts())
        assert dashboard.status_code == 200
        assert before == after
        data = dashboard.json()
        assert data["summary"] == {
            "currentMonthIncomeCzk": "2000.000000",
            "currentMonthExpenseCzk": "900.000000",
            "currentMonthNetCzk": "1100.000000",
        }
        assert data["budget"]["spentCzk"] == "900.000000"
        assert data["expenseByCategory"] == [
            {
                "categoryId": "r11f-food",
                "name": "Food",
                "icon": None,
                "color": "#00aa00",
                "amountCzk": "900.000000",
            }
        ]
        assert len(data["monthlyTrends"]) == 6
        assert all("cashValueCzk" not in item for item in [data["summary"]])
        assert all(row["id"] != "r11f-foreign-expense" for row in data["recentTransactions"])
