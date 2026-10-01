import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

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
    SnapshotGranularity,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import PriceSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.holdings.rebuild_service import HoldingRebuildService, HoldingRebuildStateError
from app.modules.investments.models import (
    ManualInvestmentCreateRequest,
    ManualInvestmentCreateResponse,
)
from app.modules.investments.service import InvestmentService
from app.modules.snapshot_refresh.api import get_manual_user_snapshot_refresh_service
from app.modules.snapshot_refresh.manual_service import (
    RecalculateUserSnapshotRefreshCommand,
    RecalculateUserSnapshotRefreshResult,
)

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r11g-internal-auth-secret-32-characters"
NOW = datetime(2026, 8, 10, 12, 0, 0)
RUN_ID = uuid4().hex[:12]
OWNER_ID = f"r11g-owner-{RUN_ID}"
VIEWER_ID = f"r11g-viewer-{RUN_ID}"
FOREIGN_ID = f"r11g-foreign-{RUN_ID}"
ACCOUNT_ID = f"r11g-account-{RUN_ID}"
FOREIGN_ACCOUNT_ID = f"r11g-foreign-account-{RUN_ID}"
SYMBOL = f"R11G{RUN_ID.upper()}"
USER_IDS = (OWNER_ID, VIEWER_ID, FOREIGN_ID)
ACCOUNT_IDS = (ACCOUNT_ID, FOREIGN_ACCOUNT_ID)

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
    async def recalculate(
        self, _command: RecalculateUserSnapshotRefreshCommand
    ) -> RecalculateUserSnapshotRefreshResult:
        return RecalculateUserSnapshotRefreshResult(
            net_worth_snapshot_id="r11g-net-worth-snapshot",
            net_worth_status="created",
            timestamp=NOW,
            granularity=SnapshotGranularity.minute,
            currency="EUR",
            calculation_version=1,
            accounts=(),
            refresh_account_count=0,
            reuse_only_account_count=0,
            created_account_snapshot_count=0,
            replayed_account_snapshot_count=0,
            reused_account_snapshot_count=0,
            selected_account_snapshot_count=0,
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
                        AssetListingModel.provider_symbol == SYMBOL,
                    )
                )
            ).all()
        )
        if listings:
            await session.execute(
                delete(PriceSnapshotModel).where(PriceSnapshotModel.listing_id.in_(listings))
            )
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
            (f"r11g-owner-member-{RUN_ID}", ACCOUNT_ID, OWNER_ID, AccountMemberRole.owner),
            (f"r11g-viewer-member-{RUN_ID}", ACCOUNT_ID, VIEWER_ID, AccountMemberRole.viewer),
            (
                f"r11g-foreign-member-{RUN_ID}",
                FOREIGN_ACCOUNT_ID,
                FOREIGN_ID,
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
    *, account_id: str = ACCOUNT_ID, key: str, action: str, **values: object
) -> dict[str, object]:
    return {
        "accountId": account_id,
        "idempotencyKey": key,
        "date": "2026-08-10",
        "type": action,
        **values,
    }


async def _concurrent_replay(
    payload: dict[str, object],
) -> tuple[ManualInvestmentCreateResponse, ManualInvestmentCreateResponse]:
    engine = _engine()
    principal = AuthenticatedPrincipal(user_id=OWNER_ID, email=f"{OWNER_ID}@example.com")

    async def execute() -> ManualInvestmentCreateResponse:
        async with AsyncSession(engine) as session:
            return await InvestmentService(
                session, snapshot_service=_ReadySnapshotService()
            ).create_manual(
                principal=principal,
                payload=ManualInvestmentCreateRequest.model_validate(payload),
            )

    try:
        first, second = await asyncio.wait_for(asyncio.gather(execute(), execute()), timeout=10)
        return first, second
    finally:
        await engine.dispose()


async def _counts_for_key(key: str) -> tuple[int, int]:
    engine = _engine()
    external_id = f"manual:{OWNER_ID}:{key}"
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


async def _seed_exact_symbol_price() -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        listing = await session.scalar(
            select(AssetListingModel).where(AssetListingModel.provider_symbol == SYMBOL)
        )
        holding = await session.scalar(
            select(HoldingModel).where(HoldingModel.account_id == ACCOUNT_ID)
        )
        assert listing is not None and holding is not None
        listing.provider = PriceSource.yahoo_finance
        holding.current_price = Decimal("13")
        holding.current_value = Decimal("78")
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        session.add_all(
            [
                PriceSnapshotModel(
                    id=f"r11g-exact-price-{RUN_ID}",
                    asset_id=listing.asset_id,
                    listing_id=listing.id,
                    price=Decimal("13"),
                    currency="EUR",
                    source=PriceSource.yahoo_finance,
                    provider_symbol=SYMBOL,
                    timestamp=now - timedelta(minutes=2),
                ),
                PriceSnapshotModel(
                    id=f"r11g-other-price-{RUN_ID}",
                    asset_id=listing.asset_id,
                    listing_id=listing.id,
                    price=Decimal("99"),
                    currency="EUR",
                    source=PriceSource.yahoo_finance,
                    provider_symbol=f"WRONG{RUN_ID.upper()}",
                    timestamp=now - timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture
def seeded_manual_data():
    _run(_seed())
    try:
        yield
    finally:
        _run(_cleanup())


def test_manual_investment_command_and_symbol_detail_on_postgresql(
    monkeypatch: pytest.MonkeyPatch,
    seeded_manual_data: None,
) -> None:
    assert DATABASE_URL is not None
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        market_evidence_source_mode="local_free",
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_manual_user_snapshot_refresh_service] = lambda: (
        _ReadySnapshotService()
    )

    buy = _payload(
        key="buy-1",
        action="buy",
        symbol=SYMBOL,
        name=f"{SYMBOL} asset",
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
        created = client.post("/api/v1/investments/manual", headers=_headers(OWNER_ID), json=buy)
        assert created.status_code == 201, created.text
        assert created.json()["replayed"] is False
        assert created.json()["holdings"]["created"] == 1
        assert created.json()["snapshot"] == {
            "status": "ready",
            "netWorthSnapshotId": "r11g-net-worth-snapshot",
            "timestamp": "2026-08-10T12:00:00.000",
        }

        replay = client.post("/api/v1/investments/manual", headers=_headers(OWNER_ID), json=buy)
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True
        assert _run(_counts_for_key("buy-1")) == (1, 3)

        conflict = dict(buy, totalAmount="101.0000000000")
        assert (
            client.post(
                "/api/v1/investments/manual",
                headers=_headers(OWNER_ID),
                json=conflict,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/investments/manual",
                headers=_headers(VIEWER_ID),
                json=_payload(key="viewer", action="deposit", totalAmount="1", totalCurrency="EUR"),
            ).status_code
            == 403
        )

        sell = client.post(
            "/api/v1/investments/manual",
            headers=_headers(OWNER_ID),
            json=_payload(
                key="sell-1",
                action="sell",
                date="2026-08-11",
                symbol=SYMBOL,
                name=f"{SYMBOL} asset",
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
                headers=_headers(OWNER_ID),
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
            headers=_headers(FOREIGN_ID),
            json=_payload(
                account_id=FOREIGN_ACCOUNT_ID,
                key="foreign-buy",
                action="buy",
                symbol=SYMBOL,
                name=f"{SYMBOL} asset",
                assetType="stock",
                quantity="2",
                pricePerUnit="10",
                priceCurrency="EUR",
                totalAmount="20",
                totalCurrency="EUR",
            ),
        )
        assert foreign.status_code == 201, foreign.text

        detail = client.get(
            f"/api/v1/investments/symbols/{SYMBOL.lower()}", headers=_headers(OWNER_ID)
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["symbol"] == SYMBOL
        assert len(body["positions"]) == 1
        assert body["positions"][0]["accountId"] == ACCOUNT_ID
        assert body["positions"][0]["quantity"] == "6.0000000000"
        assert body["positions"][0]["avgBuyPrice"] == "10.0000000000"
        assert body["positions"][0]["assetName"] == f"{SYMBOL} asset"
        assert body["positions"][0]["listingSymbol"] == SYMBOL
        assert body["positions"][0]["listingCurrency"] == "EUR"
        assert body["positions"][0]["listingBasePriority"] == 0
        assert body["positions"][0]["marketProvider"] is None
        assert body["positions"][0]["priceAmount"] is None
        assert body["positions"][0]["requestedListingId"] == body["positions"][0]["listingId"]
        assert body["positions"][0]["selectedListingId"] is None
        assert body["positions"][0]["priceFreshness"] == "unavailable"
        assert body["positions"][0]["fxEvidenceId"] is None
        assert body["positions"][0]["convertedValue"] is None
        assert body["positions"][0]["traceStatus"] == "unresolved"
        assert [event["type"] for event in body["events"]] == ["sell", "buy"]
        assert all(event["accountId"] == ACCOUNT_ID for event in body["events"])
        assert body["events"][0]["totalAmount"] == "48.0000000000"

        _run(_seed_exact_symbol_price())
        priced = client.get(f"/api/v1/investments/symbols/{SYMBOL}", headers=_headers(OWNER_ID))
        assert priced.status_code == 200, priced.text
        trace = priced.json()["positions"][0]
        assert trace["marketProvider"] == "yahoo_finance"
        assert trace["marketProviderSymbol"] == SYMBOL
        assert trace["priceAmount"] == "13.0000000000"
        assert trace["priceProviderSymbol"] == SYMBOL
        assert trace["selectedListingId"] == trace["requestedListingId"]
        assert trace["selectionReason"] == "requested_listing"
        assert trace["selectedBasePriority"] == 0
        assert trace["selectedHealth"] == "unknown"
        assert trace["selectedProvider"] == "yahoo_finance"
        assert trace["selectedProviderSymbol"] == SYMBOL
        assert trace["priceSnapshotId"] == f"r11g-exact-price-{RUN_ID}"
        assert trace["priceFreshness"] == "fresh"
        assert trace["fxEvidenceId"] is None
        assert trace["convertedValue"] is None
        assert trace["traceStatus"] == "ok"

        original_rebuild = HoldingRebuildService.rebuild

        async def fail_rebuild(*_args: object, **_kwargs: object) -> object:
            raise HoldingRebuildStateError()

        monkeypatch.setattr(HoldingRebuildService, "rebuild", fail_rebuild)
        rolled_back = client.post(
            "/api/v1/investments/manual",
            headers=_headers(OWNER_ID),
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
