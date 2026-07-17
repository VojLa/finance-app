import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import insert

from app.config.settings import Settings
from app.db.connection import close_database, create_database
from app.db.models import (
    AccountMemberModel,
    AccountMemberRole,
    AccountModel,
    AccountRelationType,
    AccountType,
    AssetListingModel,
    AssetModel,
    AssetType,
    ExchangeRateModel,
    ExchangeRateSource,
    HoldingModel,
    PriceSource,
    UserModel,
)
from app.modules.portfolio.repository import PortfolioRepository

DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_sqlalchemy_repository_reads_prisma_migrated_schema() -> None:
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        _env_file=None,
    )
    database = create_database(settings)
    assert database is not None

    now = datetime(2026, 1, 1, 12, 0, 0)
    try:
        async with database.session_factory() as session:
            await session.execute(
                insert(UserModel).values(
                    id="sqlalchemy-user",
                    email="sqlalchemy@example.test",
                    name="SQLAlchemy Test",
                    password_hash=None,
                    base_currency="EUR",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(AccountModel),
                [
                    {
                        "id": "sqlalchemy-account",
                        "name": "Broker",
                        "type": AccountType.broker,
                        "currency": "EUR",
                        "color": None,
                        "notes": "Primary investing account",
                        "is_archived": False,
                        "archived_at": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "sqlalchemy-archived",
                        "name": "Archived",
                        "type": AccountType.broker,
                        "currency": "EUR",
                        "color": None,
                        "notes": None,
                        "is_archived": True,
                        "archived_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )
            await session.execute(
                insert(AccountMemberModel),
                [
                    {
                        "id": "sqlalchemy-member",
                        "account_id": "sqlalchemy-account",
                        "user_id": "sqlalchemy-user",
                        "role": AccountMemberRole.owner,
                        "relation_type": AccountRelationType.owner,
                        "invited_by_id": None,
                        "accepted_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "sqlalchemy-archived-member",
                        "account_id": "sqlalchemy-archived",
                        "user_id": "sqlalchemy-user",
                        "role": AccountMemberRole.owner,
                        "relation_type": AccountRelationType.owner,
                        "invited_by_id": None,
                        "accepted_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )
            await session.execute(
                insert(AssetModel).values(
                    id="sqlalchemy-asset",
                    symbol="VUAA",
                    isin=None,
                    name="Vanguard S&P 500",
                    asset_type=AssetType.etf,
                    currency="USD",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(AssetListingModel).values(
                    id="sqlalchemy-listing",
                    asset_id="sqlalchemy-asset",
                    symbol="VUAA",
                    exchange="LSE",
                    mic=None,
                    currency="USD",
                    country=None,
                    provider=PriceSource.manual,
                    provider_symbol=None,
                    is_primary=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(HoldingModel).values(
                    id="sqlalchemy-holding",
                    symbol="VUAA",
                    name="Vanguard S&P 500",
                    asset_type=AssetType.etf,
                    quantity=Decimal("2"),
                    avg_buy_price=Decimal("100"),
                    currency="USD",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                    asset_id="sqlalchemy-asset",
                    listing_id="sqlalchemy-listing",
                    account_id="sqlalchemy-account",
                    calculated_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(ExchangeRateModel),
                [
                    {
                        "id": "sqlalchemy-rate-old",
                        "from_currency": "USD",
                        "to_currency": "EUR",
                        "rate": Decimal("0.80"),
                        "date": datetime(2025, 12, 31, 12, 0, 0),
                        "source": ExchangeRateSource.manual,
                        "created_at": now,
                    },
                    {
                        "id": "sqlalchemy-rate-new",
                        "from_currency": "USD",
                        "to_currency": "EUR",
                        "rate": Decimal("0.90"),
                        "date": now,
                        "source": ExchangeRateSource.manual,
                        "created_at": now,
                    },
                ],
            )

            repository = PortfolioRepository(session)
            accounts = await repository.accessible_accounts("sqlalchemy-user")
            holdings = await repository.holdings_for_accounts(["sqlalchemy-account"])
            rates = await repository.latest_exchange_rates(
                [("USD", "EUR"), ("EUR", "EUR"), ("USD", "EUR")]
            )

            assert accounts == [
                {
                    "id": "sqlalchemy-account",
                    "name": "Broker",
                    "type": "broker",
                    "currency": "EUR",
                }
            ]
            assert len(holdings) == 1
            assert holdings[0]["symbol"] == "VUAA"
            assert holdings[0]["quantity"] == Decimal("2")
            assert rates == {("EUR", "EUR"): 1.0, ("USD", "EUR"): 0.9}

            await session.rollback()
    finally:
        await close_database(database)
