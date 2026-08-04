from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetAliasProvider,
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.snapshot_refresh.executor import ExecuteUserSnapshotRefreshCommand

DATABASE_URL = os.getenv("DATABASE_URL")


def coingecko_engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


async def seed_crypto_holding(
    prefix: str,
    *,
    event_at: datetime,
    created_at: datetime,
    aliases: tuple[str, ...] = ("bitcoin",),
    listing_provider_symbol: str | None = None,
) -> tuple[str, str, str, str]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    engine = coingecko_engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="EUR",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            session.add(
                AccountModel(
                    id=account_id,
                    name="Synthetic crypto exchange",
                    type=AccountType.exchange,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol="BTC",
                    isin=None,
                    name="Synthetic Bitcoin evidence",
                    asset_type=AssetType.crypto,
                    currency="EUR",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member",
                    account_id=account_id,
                    user_id=user_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=created_at,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="BTC",
                    exchange=f"SYN-{prefix}",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.exchange,
                    provider_symbol=listing_provider_symbol or f"BTC-{prefix}",
                    is_primary=True,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            for index, alias in enumerate(aliases, start=1):
                session.add(
                    AssetAliasModel(
                        id=f"{prefix}-alias-{index}",
                        asset_id=asset_id,
                        provider=AssetAliasProvider.coingecko,
                        external_id=alias,
                        created_at=created_at,
                    )
                )
            await session.flush()
            session.add(
                HoldingModel(
                    id=f"{prefix}-holding",
                    symbol="BTC",
                    name="Synthetic Bitcoin holding",
                    asset_type=AssetType.crypto,
                    quantity=Decimal("1000"),
                    avg_buy_price=Decimal("50000"),
                    currency="EUR",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    account_id=account_id,
                    calculated_at=created_at,
                    updated_at=created_at,
                )
            )
            event_id = f"{prefix}-event"
            session.add(
                InvestmentEventModel(
                    id=event_id,
                    account_id=account_id,
                    type=InvestmentEventType.cash_deposit,
                    date=event_at,
                    source=None,
                    external_id=f"{prefix}-deposit",
                    order_id=None,
                    description="Synthetic EUR deposit",
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.flush()
            session.add(
                InvestmentMovementModel(
                    id=f"{prefix}-movement",
                    event_id=event_id,
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("1000"),
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=Decimal("1000"),
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return user_id, account_id, asset_id, listing_id


def snapshot_command(
    user_id: str,
    *,
    snapshot_at: datetime,
    calculated_at: datetime,
    created_at: datetime,
) -> ExecuteUserSnapshotRefreshCommand:
    return ExecuteUserSnapshotRefreshCommand(
        user_id=user_id,
        snapshot_timestamp=snapshot_at,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.price_refresh,
        calculation_version=1,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=False,
    )


def principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
    )
