from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
    LiabilityBalanceSource,
    MovementDirection,
    PriceSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.market_data.requirements import (
    BuildMarketEvidenceRefreshPlanCommand,
    MarketEvidenceRequirementsPlanner,
)
from app.modules.market_data.requirements_repository import (
    MarketEvidenceRequirementsRepository,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

SNAPSHOT_AT = datetime(2026, 8, 3, 12)
EVENT_AT = SNAPSHOT_AT - timedelta(days=3)
CREATED_AT = datetime(2026, 8, 3, 12, 1)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL))


@pytest.mark.asyncio
async def test_read_only_plan_uses_exact_persisted_scope_and_event_dates() -> None:
    prefix = f"r5a-plan-{uuid4()}"
    user_id = f"{prefix}-user"
    direct_account_id = f"{prefix}-account-direct"
    alias_account_id = f"{prefix}-account-alias"
    archived_account_id = f"{prefix}-account-archived"
    direct_asset_id = f"{prefix}-asset-direct"
    alias_asset_id = f"{prefix}-asset-alias"
    direct_listing_id = f"{prefix}-listing-direct"
    alias_listing_id = f"{prefix}-listing-alias"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            for account_id, archived in (
                (direct_account_id, False),
                (alias_account_id, False),
                (archived_account_id, True),
            ):
                session.add(
                    AccountModel(
                        id=account_id,
                        name=account_id,
                        type=AccountType.broker,
                        currency="EUR",
                        color=None,
                        notes=None,
                        is_archived=archived,
                        archived_at=CREATED_AT if archived else None,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            await session.flush()
            for index, account_id in enumerate(
                (direct_account_id, alias_account_id, archived_account_id)
            ):
                session.add(
                    AccountMemberModel(
                        id=f"{prefix}-member-{index}",
                        account_id=account_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=CREATED_AT,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            for asset_id in (direct_asset_id, alias_asset_id):
                session.add(
                    AssetModel(
                        id=asset_id,
                        symbol="SAME",
                        isin=None,
                        name="Exact asset",
                        asset_type=AssetType.etf,
                        currency="EUR",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            await session.flush()
            session.add_all(
                [
                    AssetListingModel(
                        id=direct_listing_id,
                        asset_id=direct_asset_id,
                        symbol="SAME",
                        exchange=f"DIRECT-{prefix}",
                        mic=None,
                        currency="EUR",
                        country=None,
                        provider=PriceSource.yahoo_finance,
                        provider_symbol=f"{prefix}-DIRECT-EXACT",
                        is_primary=False,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetListingModel(
                        id=alias_listing_id,
                        asset_id=alias_asset_id,
                        symbol="SAME",
                        exchange=f"ALIAS-{prefix}",
                        mic=None,
                        currency="EUR",
                        country=None,
                        provider=PriceSource.broker,
                        provider_symbol=f"{prefix}-BROKER-ONLY",
                        is_primary=False,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                ]
            )
            await session.flush()
            session.add(
                AssetAliasModel(
                    id=f"{prefix}-alias",
                    asset_id=alias_asset_id,
                    provider=AssetAliasProvider.coingecko,
                    external_id=f"{prefix}-exact-alias-id",
                    created_at=CREATED_AT,
                )
            )
            for index, (account_id, asset_id, listing_id) in enumerate(
                (
                    (direct_account_id, direct_asset_id, direct_listing_id),
                    (alias_account_id, alias_asset_id, alias_listing_id),
                    (archived_account_id, direct_asset_id, direct_listing_id),
                )
            ):
                session.add(
                    HoldingModel(
                        id=f"{prefix}-holding-{index}",
                        symbol="SAME",
                        name="Exact holding",
                        asset_type=AssetType.etf,
                        quantity=Decimal("2"),
                        avg_buy_price=Decimal("100"),
                        currency="USD",
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        asset_id=asset_id,
                        listing_id=listing_id,
                        account_id=account_id,
                        calculated_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            event_id = f"{prefix}-event"
            session.add(
                InvestmentEventModel(
                    id=event_id,
                    account_id=direct_account_id,
                    type=InvestmentEventType.trade,
                    date=EVENT_AT,
                    source=None,
                    external_id=None,
                    order_id=None,
                    description=None,
                    realized_pnl=Decimal("4"),
                    realized_pnl_currency="CHF",
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            await session.flush()
            session.add(
                InvestmentMovementModel(
                    id=f"{prefix}-movement",
                    event_id=event_id,
                    account_id=direct_account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity=Decimal("20"),
                    currency="GBP",
                    price_per_unit=None,
                    value_amount=Decimal("20"),
                    value_currency="GBP",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            session.add(
                TransactionModel(
                    id=f"{prefix}-transaction",
                    date=EVENT_AT + timedelta(hours=1),
                    booking_date=None,
                    amount=Decimal("10"),
                    currency="CAD",
                    reporting_amount=None,
                    reporting_currency=None,
                    type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    description=None,
                    note=None,
                    counterparty=None,
                    external_id=None,
                    is_reviewed=False,
                    archived_at=None,
                    deleted_at=None,
                    category_id=None,
                    account_id=alias_account_id,
                    import_batch_id=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            session.add(
                LiabilityBalanceModel(
                    id=f"{prefix}-liability",
                    account_id=direct_account_id,
                    effective_at=EVENT_AT,
                    currency="JPY",
                    outstanding_principal=Decimal("100"),
                    accrued_interest=Decimal("0"),
                    fees_outstanding=Decimal("0"),
                    total_outstanding=Decimal("100"),
                    source=LiabilityBalanceSource.manual,
                    external_id=None,
                    created_at=CREATED_AT,
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            prices_before = await session.scalar(
                select(func.count()).select_from(PriceSnapshotModel)
            )
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            repository = MarketEvidenceRequirementsRepository(session)
            async with session.begin():
                await repository.set_transaction_repeatable_read_only()
                plan = await MarketEvidenceRequirementsPlanner(
                    session,
                    price_sources=frozenset({PriceSource.yahoo_finance, PriceSource.coingecko}),
                    fx_source=ExchangeRateSource.ecb,
                    repository=repository,
                ).build(
                    BuildMarketEvidenceRefreshPlanCommand(
                        user_id,
                        SNAPSHOT_AT,
                    )
                )
            assert not session.in_transaction()
            prices_after = await session.scalar(
                select(func.count()).select_from(PriceSnapshotModel)
            )
            rates_after = await session.scalar(select(func.count()).select_from(ExchangeRateModel))

        assert prices_after == prices_before
        assert rates_after == rates_before
        assert {item.account_id for item in plan.price_requirements} == {
            direct_account_id,
            alias_account_id,
        }
        assert {
            (item.listing_id, item.provider, item.provider_symbol)
            for item in plan.price_requirements
        } == {
            (
                direct_listing_id,
                PriceSource.yahoo_finance,
                f"{prefix}-DIRECT-EXACT",
            ),
            (
                alias_listing_id,
                PriceSource.coingecko,
                f"{prefix}-exact-alias-id",
            ),
        }
        assert all(archived_account_id != item.account_id for item in plan.price_requirements)
        fx_identities = {
            (item.from_currency, item.to_currency, item.through, item.provider)
            for item in plan.fx_requirements
        }
        assert ("EUR", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in fx_identities
        assert ("USD", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in fx_identities
        assert ("GBP", "CZK", EVENT_AT, ExchangeRateSource.ecb) in fx_identities
        assert ("CHF", "CZK", EVENT_AT, ExchangeRateSource.ecb) in fx_identities
        assert ("JPY", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in fx_identities
        assert (
            "CAD",
            "CZK",
            EVENT_AT + timedelta(hours=1),
            ExchangeRateSource.ecb,
        ) in fx_identities
        assert plan.fx_requirements == tuple(
            sorted(
                plan.fx_requirements,
                key=lambda item: (
                    item.from_currency,
                    item.to_currency,
                    item.through,
                    item.provider.value,
                ),
            )
        )
    finally:
        await engine.dispose()
