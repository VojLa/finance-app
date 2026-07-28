from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.snapshots.api import get_snapshot_clock
from app.modules.snapshots.manual_service import (
    AccountSnapshotUnavailableError,
    ManualAccountSnapshotService,
    RecalculateAccountSnapshotCommand,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriter,
    AccountSnapshotWriteResult,
    WriteAccountSnapshotCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
NOW = datetime(2035, 7, 28, 10, 20)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        account_ids = tuple(
            await session.scalars(
                select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            )
        )
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
        if account_ids:
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.account_id.in_(account_ids)
                )
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
        await session.execute(
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-")))
        if account_ids:
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.startswith(f"{prefix}-")))
        await session.commit()
    await engine.dispose()


async def _seed_account(
    prefix: str,
    *,
    account_type: AccountType = AccountType.broker,
    role: AccountMemberRole = AccountMemberRole.owner,
    archived: bool = False,
    with_investment: bool = False,
    with_price_ambiguity: bool = False,
) -> tuple[str, str]:
    account_id = f"{prefix}-account"
    user_id = f"{prefix}-user"
    engine = _engine()
    async with AsyncSession(engine) as session:
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
        session.add(
            AccountModel(
                id=account_id,
                name=prefix,
                type=account_type,
                currency="CZK",
                color=None,
                notes=None,
                is_archived=archived,
                archived_at=NOW if archived else None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-member",
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
        if with_investment or with_price_ambiguity:
            asset_id = f"{prefix}-asset"
            listing_id = f"{prefix}-listing"
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol="AMB",
                    isin=None,
                    name="Ambiguous",
                    asset_type=AssetType.stock,
                    currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="AMB",
                    exchange="test",
                    mic=None,
                    currency="CZK",
                    country=None,
                    provider=PriceSource.manual,
                    provider_symbol="AMB",
                    is_primary=False,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                HoldingModel(
                    id=f"{prefix}-holding",
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    symbol="AMB",
                    name="Ambiguous",
                    asset_type=AssetType.stock,
                    quantity=Decimal("1"),
                    avg_buy_price=Decimal("10"),
                    currency="CZK",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                    calculated_at=NOW,
                    updated_at=NOW,
                )
            )
            if with_price_ambiguity:
                session.add_all(
                    [
                        PriceSnapshotModel(
                            id=f"{prefix}-price-a",
                            asset_id=asset_id,
                            listing_id=listing_id,
                            price=Decimal("12"),
                            currency="CZK",
                            source=PriceSource.manual,
                            timestamp=NOW,
                            created_at=NOW,
                        ),
                        PriceSnapshotModel(
                            id=f"{prefix}-price-b",
                            asset_id=asset_id,
                            listing_id=listing_id,
                            price=Decimal("12"),
                            currency="CZK",
                            source=PriceSource.broker,
                            timestamp=NOW,
                            created_at=NOW,
                        ),
                    ]
                )
            else:
                event_at = NOW - timedelta(days=1)
                holding = await session.get(HoldingModel, f"{prefix}-holding")
                listing = await session.get(AssetListingModel, listing_id)
                asset = await session.get(AssetModel, asset_id)
                assert holding is not None and listing is not None and asset is not None
                holding.quantity = Decimal("2")
                holding.avg_buy_price = Decimal("10")
                holding.currency = "EUR"
                listing.currency = "EUR"
                asset.currency = "EUR"
                session.add_all(
                    [
                        PriceSnapshotModel(
                            id=f"{prefix}-price",
                            asset_id=asset_id,
                            listing_id=listing_id,
                            price=Decimal("15"),
                            currency="EUR",
                            source=PriceSource.broker,
                            timestamp=NOW,
                            created_at=NOW,
                        ),
                        ExchangeRateModel(
                            id=f"{prefix}-event-rate",
                            from_currency="EUR",
                            to_currency="CZK",
                            rate=Decimal("20"),
                            date=event_at,
                            source=ExchangeRateSource.ecb,
                            created_at=event_at,
                        ),
                        ExchangeRateModel(
                            id=f"{prefix}-snapshot-rate",
                            from_currency="EUR",
                            to_currency="CZK",
                            rate=Decimal("25"),
                            date=NOW,
                            source=ExchangeRateSource.ecb,
                            created_at=NOW,
                        ),
                        InvestmentEventModel(
                            id=f"{prefix}-deposit",
                            account_id=account_id,
                            type=InvestmentEventType.cash_deposit,
                            date=event_at,
                            source=ImportSource.trading212,
                            external_id=None,
                            order_id=None,
                            description=None,
                            realized_pnl=None,
                            realized_pnl_currency=None,
                            import_batch_id=None,
                            archived_at=None,
                            deleted_at=None,
                            created_at=event_at,
                            updated_at=event_at,
                        ),
                        InvestmentEventModel(
                            id=f"{prefix}-trade",
                            account_id=account_id,
                            type=InvestmentEventType.trade,
                            date=event_at,
                            source=ImportSource.trading212,
                            external_id=f"{prefix}-trade",
                            order_id=None,
                            description="AMB",
                            realized_pnl=None,
                            realized_pnl_currency=None,
                            import_batch_id=None,
                            archived_at=None,
                            deleted_at=None,
                            created_at=event_at,
                            updated_at=event_at,
                        ),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        InvestmentMovementModel(
                            id=f"{prefix}-deposit-cash",
                            event_id=f"{prefix}-deposit",
                            account_id=account_id,
                            asset_id=None,
                            listing_id=None,
                            kind=InvestmentMovementKind.cash,
                            direction=MovementDirection.incoming,
                            quantity=Decimal("10"),
                            currency="EUR",
                            price_per_unit=None,
                            value_amount=Decimal("10"),
                            value_currency="EUR",
                            source_symbol=None,
                            source_asset_type=None,
                            note=None,
                            created_at=event_at,
                            updated_at=event_at,
                        ),
                        InvestmentMovementModel(
                            id=f"{prefix}-trade-asset",
                            event_id=f"{prefix}-trade",
                            account_id=account_id,
                            asset_id=asset_id,
                            listing_id=listing_id,
                            kind=InvestmentMovementKind.asset,
                            direction=MovementDirection.incoming,
                            quantity=Decimal("2"),
                            currency="AMB",
                            price_per_unit=Decimal("10"),
                            value_amount=Decimal("20"),
                            value_currency="EUR",
                            source_symbol="AMB",
                            source_asset_type=AssetType.stock,
                            note=None,
                            created_at=event_at,
                            updated_at=event_at,
                        ),
                        InvestmentMovementModel(
                            id=f"{prefix}-trade-cash",
                            event_id=f"{prefix}-trade",
                            account_id=account_id,
                            asset_id=None,
                            listing_id=None,
                            kind=InvestmentMovementKind.cash,
                            direction=MovementDirection.outgoing,
                            quantity=Decimal("20"),
                            currency="EUR",
                            price_per_unit=None,
                            value_amount=Decimal("20"),
                            value_currency="EUR",
                            source_symbol=None,
                            source_asset_type=None,
                            note=None,
                            created_at=event_at,
                            updated_at=event_at,
                        ),
                    ]
                )
        await session.commit()
    await engine.dispose()
    return account_id, user_id


async def _add_nonmember(prefix: str) -> str:
    user_id = f"{prefix}-foreign"
    engine = _engine()
    async with AsyncSession(engine) as session:
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
        await session.commit()
    await engine.dispose()
    return user_id


def _call(account_id: str, user_id: str, *, now: datetime = NOW):
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret="test-secret-that-is-long-enough-for-auth",
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user_id)
    app.dependency_overrides[get_snapshot_clock] = lambda: lambda: now
    with TestClient(app) as client:
        return client.post(f"/api/v1/accounts/{account_id}/snapshots/recalculate")


async def _counts(account_id: str) -> tuple[int, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        snapshots = (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
        items = (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotItemModel)
                .join(
                    AccountSnapshotModel,
                    AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
                )
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
        return snapshots, items


@pytest.mark.parametrize(
    "role",
    [AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor],
)
def test_persisted_write_roles_create_replay_and_next_bucket(
    role: AccountMemberRole,
) -> None:
    prefix = f"i5e-{role.value}"
    asyncio.run(_cleanup(prefix))
    account_id, user_id = asyncio.run(_seed_account(prefix, role=role, with_investment=True))
    try:
        first = _call(account_id, user_id)
        replay = _call(account_id, user_id, now=NOW + timedelta(seconds=59))
        next_bucket = _call(account_id, user_id, now=NOW + timedelta(minutes=1))

        assert first.status_code == replay.status_code == next_bucket.status_code == 200
        assert first.json()["status"] == "created"
        assert first.json()["itemCount"] == 1
        assert replay.json()["status"] == "replayed"
        assert first.json()["snapshotId"] == replay.json()["snapshotId"]
        assert first.json()["timestamp"] == "2035-07-28T10:20:00.000"
        assert next_bucket.json()["status"] == "created"
        assert next_bucket.json()["snapshotId"] != first.json()["snapshotId"]
        assert asyncio.run(_counts(account_id)) == (2, 2)
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.parametrize(
    ("access", "role"),
    [
        ("viewer", AccountMemberRole.viewer),
        ("nonmember", AccountMemberRole.owner),
        ("archived", AccountMemberRole.owner),
    ],
)
def test_hidden_account_matrix_creates_nothing(
    access: str,
    role: AccountMemberRole,
) -> None:
    prefix = f"i5e-hidden-{access}"
    asyncio.run(_cleanup(prefix))
    account_id, member_id = asyncio.run(
        _seed_account(prefix, role=role, archived=access == "archived")
    )
    user_id = asyncio.run(_add_nonmember(prefix)) if access == "nonmember" else member_id
    try:
        response = _call(account_id, user_id)
        missing = _call(f"{prefix}-missing", user_id)
        assert response.status_code == missing.status_code == 404
        assert response.json()["error"]["code"] == missing.json()["error"]["code"]
        assert response.json()["error"]["message"] == missing.json()["error"]["message"]
        assert asyncio.run(_counts(account_id)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.parametrize("account_type", [AccountType.bank, AccountType.credit_card])
def test_unsupported_accounts_map_to_generic_conflict_and_write_nothing(
    account_type: AccountType,
) -> None:
    prefix = f"i5e-unsupported-{account_type.value}"
    asyncio.run(_cleanup(prefix))
    account_id, user_id = asyncio.run(_seed_account(prefix, account_type=account_type))
    try:
        response = _call(account_id, user_id)
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "account_snapshot_unavailable",
            "message": "Account snapshot cannot be created from the current account data.",
            "request_id": response.headers["x-request-id"],
        }
        assert asyncio.run(_counts(account_id)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


def test_ambiguous_price_is_generic_and_creates_no_snapshot() -> None:
    prefix = "i5e-ambiguous-price"
    asyncio.run(_cleanup(prefix))
    account_id, user_id = asyncio.run(_seed_account(prefix, with_price_ambiguity=True))
    try:
        response = _call(account_id, user_id)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "account_snapshot_unavailable"
        assert "price" not in response.json()["error"]["message"].lower()
        assert asyncio.run(_counts(account_id)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


def test_existing_physical_conflict_is_not_repaired() -> None:
    prefix = "i5e-conflict"
    asyncio.run(_cleanup(prefix))
    account_id, user_id = asyncio.run(_seed_account(prefix))
    try:
        created = _call(account_id, user_id)
        assert created.status_code == 200

        async def corrupt() -> None:
            engine = _engine()
            async with AsyncSession(engine) as session:
                snapshot = await session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == account_id
                    )
                )
                assert snapshot is not None
                snapshot.cash_value = Decimal("1")
                await session.commit()
            await engine.dispose()

        asyncio.run(corrupt())
        replay = _call(account_id, user_id)
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "account_snapshot_conflict"

        async def persisted_cash() -> Decimal:
            engine = _engine()
            async with AsyncSession(engine) as session:
                value = await session.scalar(
                    select(AccountSnapshotModel.cash_value).where(
                        AccountSnapshotModel.account_id == account_id
                    )
                )
            await engine.dispose()
            assert value is not None
            return value

        assert asyncio.run(persisted_cash()) == Decimal("1.000000")
        assert asyncio.run(_counts(account_id)) == (1, 0)
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.asyncio
async def test_account_archived_after_authorization_is_rejected_by_writer_lock() -> None:
    prefix = "i5e-archive-race"
    await _cleanup(prefix)
    account_id, user_id = await _seed_account(prefix)
    engine = _engine()

    class ArchivingWriter:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def write(
            self,
            command: WriteAccountSnapshotCommand,
        ) -> AccountSnapshotWriteResult:
            other_engine = _engine()
            async with AsyncSession(other_engine) as archive_session:
                account = await archive_session.get(AccountModel, account_id)
                assert account is not None
                account.is_archived = True
                account.archived_at = NOW
                await archive_session.commit()
            await other_engine.dispose()
            return await AccountSnapshotWriter(self.session).write(command)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(AccountSnapshotUnavailableError):
                await ManualAccountSnapshotService(
                    session,
                    clock=lambda: NOW,
                    writer_factory=ArchivingWriter,
                ).recalculate(
                    RecalculateAccountSnapshotCommand(
                        principal=_principal(user_id),
                        account_id=account_id,
                    )
                )
        assert await _counts(account_id) == (0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)
