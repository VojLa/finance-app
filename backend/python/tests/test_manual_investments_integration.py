import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.holdings.rebuild_service import HoldingRebuildService, HoldingRebuildStateError
from app.modules.investments.models import ManualInvestmentCreateRequest
from app.modules.investments.service import InvestmentService
from app.modules.snapshot_refresh.api import get_manual_user_snapshot_refresh_service

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r11g-internal-auth-secret-32-characters"
NOW = datetime(2026, 8, 10, 12, 0, 0)
USER_IDS = ("r11g-owner", "r11g-viewer", "r11g-foreign")
ACCOUNT_IDS = ("r11g-account", "r11g-foreign-account")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


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


class _ReadySnapshotService:
    async def recalculate(self, _command: object) -> object:
        return SimpleNamespace(
            net_worth_snapshot_id="r11g-net-worth-snapshot",
            timestamp=NOW,
        )


async def _cleanup() -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        await session.execute(delete(HoldingModel).where(HoldingModel.account_id.in_(ACCOUNT_IDS)))
        await session.execute(
            delete(InvestmentMovementModel).where(
                InvestmentMovementModel.account_id.in_(ACCOUNT_IDS)
            )
        )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.account_id.in_(ACCOUNT_IDS))
        )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNT_IDS))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNT_IDS)))
        listings = tuple(
            (
                await session.scalars(
                    select(AssetListingModel.id).where(
                        AssetListingModel.provider == PriceSource.manual,
                        AssetListingModel.provider_symbol == "R11G",
                    )
                )
            ).all()
        )
        if listings:
            asset_ids = tuple(
                (
                    await session.scalars(
                        select(AssetListingModel.asset_id).where(AssetListingModel.id.in_(listings))
                    )
                ).all()
            )
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id.in_(listings))
            )
            await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))
        await session.commit()
    await engine.dispose()


async def _seed() -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        await _cleanup()
        for user_id in USER_IDS:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        for account_id in ACCOUNT_IDS:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.broker,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        await session.flush()
        for member_id, account_id, user_id, role in (
            ("r11g-owner-member", "r11g-account", "r11g-owner", AccountMemberRole.owner),
            ("r11g-viewer-member", "r11g-account", "r11g-viewer", AccountMemberRole.viewer),
            (
                "r11g-foreign-member",
                "r11g-foreign-account",
                "r11g-foreign",
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
                    accepted_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        await session.commit()
    await engine.dispose()


def _payload(
    *, account_id: str = "r11g-account", key: str, action: str, **values: object
) -> dict[str, object]:
    return {
        "accountId": account_id,
        "idempotencyKey": key,
        "date": "2026-08-10",
        "type": action,
        **values,
    }


async def _concurrent_replay(payload: dict[str, object]) -> tuple[object, object]:
    engine = _engine()
    principal = AuthenticatedPrincipal(user_id="r11g-owner", email="r11g-owner@example.com")

    async def execute() -> object:
        async with AsyncSession(engine) as session:
            return await InvestmentService(
                session, snapshot_service=_ReadySnapshotService()
            ).create_manual(
                principal=principal,
                payload=ManualInvestmentCreateRequest.model_validate(payload),
            )

    try:
        first, second = await asyncio.gather(execute(), execute())
        return first, second
    finally:
        await engine.dispose()


async def _counts_for_key(key: str) -> tuple[int, int]:
    engine = _engine()
    external_id = f"manual:r11g-owner:{key}"
    async with AsyncSession(engine) as session:
        event_ids = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.external_id == external_id
                    )
                )
            ).all()
        )
        result = (
            len(event_ids),
            int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(InvestmentMovementModel)
                        .where(InvestmentMovementModel.event_id.in_(event_ids))
                    )
                )
                or 0
            ),
        )
    await engine.dispose()
    return result


def test_manual_investment_command_and_symbol_detail_on_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    app = create_app(settings)
    app.dependency_overrides[get_manual_user_snapshot_refresh_service] = lambda: (
        _ReadySnapshotService()
    )

    buy = _payload(
        key="buy-1",
        action="buy",
        symbol="R11G",
        name="R11G asset",
        assetType="stock",
        quantity="10.0000000000",
        pricePerUnit="10.0000000000",
        priceCurrency="EUR",
        totalAmount="100.0000000000",
        totalCurrency="EUR",
        fee="1.0000000000",
        feeCurrency="EUR",
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/v1/investments/manual", headers=_headers("r11g-owner"), json=buy
        )
        assert created.status_code == 201, created.text
        assert created.json()["replayed"] is False
        assert created.json()["holdings"]["created"] == 1
        assert created.json()["snapshot"] == {
            "status": "ready",
            "netWorthSnapshotId": "r11g-net-worth-snapshot",
            "timestamp": "2026-08-10T12:00:00.000",
        }

        replay = client.post("/api/v1/investments/manual", headers=_headers("r11g-owner"), json=buy)
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True
        assert _run(_counts_for_key("buy-1")) == (1, 3)

        conflict = dict(buy, totalAmount="101.0000000000")
        assert (
            client.post(
                "/api/v1/investments/manual",
                headers=_headers("r11g-owner"),
                json=conflict,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/investments/manual",
                headers=_headers("r11g-viewer"),
                json=_payload(key="viewer", action="deposit", totalAmount="1", totalCurrency="EUR"),
            ).status_code
            == 403
        )

        sell = client.post(
            "/api/v1/investments/manual",
            headers=_headers("r11g-owner"),
            json=_payload(
                key="sell-1",
                action="sell",
                symbol="R11G",
                name="R11G asset",
                assetType="stock",
                quantity="4.0000000000",
                pricePerUnit="12.0000000000",
                priceCurrency="EUR",
                totalAmount="48.0000000000",
                totalCurrency="EUR",
            ),
        )
        assert sell.status_code == 201, sell.text
        for key, action in (("deposit-1", "deposit"), ("withdrawal-1", "withdrawal")):
            response = client.post(
                "/api/v1/investments/manual",
                headers=_headers("r11g-owner"),
                json=_payload(
                    key=key,
                    action=action,
                    totalAmount="25.5000000000",
                    totalCurrency="EUR",
                ),
            )
            assert response.status_code == 201, response.text

        foreign = client.post(
            "/api/v1/investments/manual",
            headers=_headers("r11g-foreign"),
            json=_payload(
                account_id="r11g-foreign-account",
                key="foreign-buy",
                action="buy",
                symbol="R11G",
                name="R11G asset",
                assetType="stock",
                quantity="2",
                pricePerUnit="10",
                priceCurrency="EUR",
                totalAmount="20",
                totalCurrency="EUR",
            ),
        )
        assert foreign.status_code == 201, foreign.text

        detail = client.get("/api/v1/investments/symbols/r11g", headers=_headers("r11g-owner"))
        assert detail.status_code == 200
        body = detail.json()
        assert body["symbol"] == "R11G"
        assert len(body["positions"]) == 1
        assert body["positions"][0]["accountId"] == "r11g-account"
        assert body["positions"][0]["quantity"] == "6.0000000000"
        assert body["positions"][0]["avgBuyPrice"] == "10.0000000000"
        assert [event["type"] for event in body["events"]] == ["sell", "buy"]
        assert all(event["accountId"] == "r11g-account" for event in body["events"])
        assert body["events"][0]["totalAmount"] == "48.0000000000"

        original_rebuild = HoldingRebuildService.rebuild

        async def fail_rebuild(*_args: object, **_kwargs: object) -> object:
            raise HoldingRebuildStateError()

        monkeypatch.setattr(HoldingRebuildService, "rebuild", fail_rebuild)
        rolled_back = client.post(
            "/api/v1/investments/manual",
            headers=_headers("r11g-owner"),
            json=_payload(
                key="rollback",
                action="deposit",
                totalAmount="9",
                totalCurrency="EUR",
            ),
        )
        assert rolled_back.status_code == 409
        assert _run(_counts_for_key("rollback")) == (0, 0)
        monkeypatch.setattr(HoldingRebuildService, "rebuild", original_rebuild)

    concurrent_payload = _payload(
        key="concurrent",
        action="deposit",
        totalAmount="7.2500000000",
        totalCurrency="EUR",
    )
    first, second = _run(_concurrent_replay(concurrent_payload))
    assert {first.replayed, second.replayed} == {False, True}
    assert _run(_counts_for_key("concurrent")) == (1, 1)

    _run(_cleanup())
