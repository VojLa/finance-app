from enum import StrEnum

from sqlalchemy.dialects import postgresql


class AccountMemberRole(StrEnum):
    owner = "owner"
    admin = "admin"
    viewer = "viewer"
    editor = "editor"


class AccountRelationType(StrEnum):
    owner = "owner"
    joint_owner = "joint_owner"
    manager = "manager"
    beneficiary = "beneficiary"
    collaborator = "collaborator"


class AccountType(StrEnum):
    bank = "bank"
    cash = "cash"
    savings = "savings"
    broker = "broker"
    exchange = "exchange"
    crypto_wallet = "crypto_wallet"
    credit_card = "credit_card"
    loan = "loan"
    mortgage = "mortgage"


class AssetType(StrEnum):
    stock = "stock"
    etf = "etf"
    crypto = "crypto"
    commodity = "commodity"
    cash = "cash"
    bond = "bond"
    other = "other"


class PriceSource(StrEnum):
    coingecko = "coingecko"
    yahoo_finance = "yahoo_finance"
    stooq = "stooq"
    manual = "manual"
    broker = "broker"
    exchange = "exchange"


class ExchangeRateSource(StrEnum):
    cnb = "cnb"
    ecb = "ecb"
    yahoo_finance = "yahoo_finance"
    manual = "manual"
    broker = "broker"
    exchange = "exchange"


ACCOUNT_MEMBER_ROLE_DB = postgresql.ENUM(
    AccountMemberRole,
    name="AccountMemberRole",
    schema="public",
    create_type=False,
)
ACCOUNT_RELATION_TYPE_DB = postgresql.ENUM(
    AccountRelationType,
    name="AccountRelationType",
    schema="public",
    create_type=False,
)
ACCOUNT_TYPE_DB = postgresql.ENUM(
    AccountType,
    name="AccountType",
    schema="public",
    create_type=False,
)
ASSET_TYPE_DB = postgresql.ENUM(
    AssetType,
    name="AssetType",
    schema="public",
    create_type=False,
)
PRICE_SOURCE_DB = postgresql.ENUM(
    PriceSource,
    name="PriceSource",
    schema="public",
    create_type=False,
)
EXCHANGE_RATE_SOURCE_DB = postgresql.ENUM(
    ExchangeRateSource,
    name="ExchangeRateSource",
    schema="public",
    create_type=False,
)
