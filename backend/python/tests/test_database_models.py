from typing import cast

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import ENUM

from app.db.base import Base
from app.db.models import ExchangeRateModel, HoldingModel

EXPECTED_COLUMNS = {
    "User": {
        "id",
        "email",
        "name",
        "passwordHash",
        "baseCurrency",
        "createdAt",
        "updatedAt",
    },
    "Account": {
        "id",
        "name",
        "type",
        "currency",
        "color",
        "isArchived",
        "archivedAt",
        "createdAt",
        "updatedAt",
    },
    "AccountMember": {
        "id",
        "accountId",
        "userId",
        "role",
        "relationType",
        "invitedById",
        "acceptedAt",
        "createdAt",
        "updatedAt",
    },
    "Asset": {
        "id",
        "symbol",
        "isin",
        "name",
        "assetType",
        "currency",
        "createdAt",
        "updatedAt",
    },
    "AssetListing": {
        "id",
        "assetId",
        "symbol",
        "exchange",
        "mic",
        "currency",
        "country",
        "provider",
        "providerSymbol",
        "isPrimary",
        "createdAt",
        "updatedAt",
    },
    "Holding": {
        "id",
        "symbol",
        "name",
        "assetType",
        "quantity",
        "avgBuyPrice",
        "currency",
        "currentPrice",
        "currentValue",
        "unrealizedPnl",
        "realizedPnl",
        "assetId",
        "listingId",
        "accountId",
        "calculatedAt",
        "updatedAt",
    },
    "ExchangeRate": {
        "id",
        "fromCurrency",
        "toCurrency",
        "rate",
        "date",
        "source",
        "createdAt",
    },
}


def test_first_persistence_slice_maps_all_expected_columns() -> None:
    tables = {table.name: table for table in Base.metadata.tables.values()}

    assert set(tables) == set(EXPECTED_COLUMNS)
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        assert set(tables[table_name].columns.keys()) == expected_columns
        assert tables[table_name].schema == "public"


def test_financial_numeric_precision_matches_prisma_schema() -> None:
    quantity = HoldingModel.__table__.c.quantity.type
    average_price = HoldingModel.__table__.c.avgBuyPrice.type
    exchange_rate = ExchangeRateModel.__table__.c.rate.type

    assert isinstance(quantity, Numeric)
    assert (quantity.precision, quantity.scale) == (28, 10)
    assert isinstance(average_price, Numeric)
    assert (average_price.precision, average_price.scale) == (28, 10)
    assert isinstance(exchange_rate, Numeric)
    assert (exchange_rate.precision, exchange_rate.scale) == (18, 8)


def test_postgresql_enums_reuse_existing_types() -> None:
    enum_columns = [
        Base.metadata.tables["public.Account"].c.type,
        Base.metadata.tables["public.AccountMember"].c.role,
        Base.metadata.tables["public.AccountMember"].c.relationType,
        Base.metadata.tables["public.Asset"].c.assetType,
        Base.metadata.tables["public.AssetListing"].c.provider,
        Base.metadata.tables["public.ExchangeRate"].c.source,
    ]
    enum_types = [cast(ENUM, column.type) for column in enum_columns]

    assert all(isinstance(enum_type, ENUM) for enum_type in enum_types)
    assert {enum_type.name for enum_type in enum_types} == {
        "AccountType",
        "AccountMemberRole",
        "AccountRelationType",
        "AssetType",
        "PriceSource",
        "ExchangeRateSource",
    }
    assert all(enum_type.create_type is False for enum_type in enum_types)
