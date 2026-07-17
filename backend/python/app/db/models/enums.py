from enum import StrEnum

from sqlalchemy.dialects import postgresql


def postgres_enum(enum_class: type[StrEnum], *, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(
        enum_class,
        name=name,
        schema="public",
        create_type=False,
        values_callable=lambda enum: [member.value for member in enum],
    )


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


class AccountInviteStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


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


class TransactionType(StrEnum):
    income = "income"
    expense = "expense"
    transfer = "transfer"


class TransactionClassification(StrEnum):
    real_income = "real_income"
    real_expense = "real_expense"
    internal_transfer = "internal_transfer"
    investment_transfer = "investment_transfer"
    loan_given = "loan_given"
    loan_received = "loan_received"
    loan_repayment = "loan_repayment"
    refund = "refund"
    cash_exchange = "cash_exchange"
    credit_card_payment = "credit_card_payment"
    ignored = "ignored"
    needs_review = "needs_review"


class CounterpartyType(StrEnum):
    merchant = "merchant"
    family = "family"
    partner = "partner"
    friend = "friend"
    employer = "employer"
    broker = "broker"
    exchange = "exchange"
    bank = "bank"
    service_provider = "service_provider"
    other = "other"


class AliasMatchType(StrEnum):
    exact = "exact"
    contains = "contains"
    starts_with = "starts_with"
    ends_with = "ends_with"


class CategoryType(StrEnum):
    expense = "expense"
    income = "income"
    both = "both"


class RuleField(StrEnum):
    description = "description"
    counterparty = "counterparty"


class RuleOperator(StrEnum):
    contains = "contains"
    equals = "equals"
    starts_with = "starts_with"
    ends_with = "ends_with"
    greater_than = "greater_than"
    less_than = "less_than"


class BudgetPeriodType(StrEnum):
    monthly = "monthly"
    weekly = "weekly"
    yearly = "yearly"
    custom = "custom"


class BudgetAlertType(StrEnum):
    approaching_limit = "approaching_limit"
    exceeded = "exceeded"
    reset = "reset"


class AssetAliasProvider(StrEnum):
    coingecko = "coingecko"
    yahoo_finance = "yahoo_finance"
    stooq = "stooq"
    broker = "broker"
    exchange = "exchange"


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
    manual = "manual"
    broker = "broker"
    exchange = "exchange"
    yahoo_finance = "yahoo_finance"


class InvestmentEventType(StrEnum):
    trade = "trade"
    cash_deposit = "cash_deposit"
    cash_withdrawal = "cash_withdrawal"
    dividend = "dividend"
    interest = "interest"
    currency_conversion = "currency_conversion"
    asset_transfer = "asset_transfer"
    fee = "fee"
    staking_reward = "staking_reward"
    airdrop = "airdrop"
    adjustment = "adjustment"


class InvestmentMovementKind(StrEnum):
    asset = "asset"
    cash = "cash"
    fee = "fee"
    tax = "tax"


class MovementDirection(StrEnum):
    incoming = "in"
    outgoing = "out"


class ImportSource(StrEnum):
    raiffeisenbank = "raiffeisenbank"
    trading212 = "trading212"
    anycoin = "anycoin"
    manual = "manual"


class ImportStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    partially_completed = "partially_completed"
    cancelled = "cancelled"


class ImportRowStatus(StrEnum):
    pending = "pending"
    imported = "imported"
    skipped = "skipped"
    duplicate = "duplicate"
    failed = "failed"
    needs_review = "needs_review"


class ImportLogLevel(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class ImportLogEvent(StrEnum):
    started = "started"
    parse_error = "parse_error"
    validation_failed = "validation_failed"
    dedup_skipped = "dedup_skipped"
    holdings_recalculated = "holdings_recalculated"
    snapshots_recalculated = "snapshots_recalculated"
    snapshot_validation_failed = "snapshot_validation_failed"
    completed = "completed"
    failed = "failed"


class SnapshotGranularity(StrEnum):
    minute = "minute"
    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class SnapshotSource(StrEnum):
    import_event = "import_event"
    price_refresh = "price_refresh"
    holdings_recalculation = "holdings_recalculation"
    scheduled = "scheduled"
    manual_recalculation = "manual_recalculation"


ACCOUNT_MEMBER_ROLE_DB = postgres_enum(AccountMemberRole, name="AccountMemberRole")
ACCOUNT_RELATION_TYPE_DB = postgres_enum(AccountRelationType, name="AccountRelationType")
ACCOUNT_INVITE_STATUS_DB = postgres_enum(AccountInviteStatus, name="AccountInviteStatus")
ACCOUNT_TYPE_DB = postgres_enum(AccountType, name="AccountType")
TRANSACTION_TYPE_DB = postgres_enum(TransactionType, name="TransactionType")
TRANSACTION_CLASSIFICATION_DB = postgres_enum(
    TransactionClassification,
    name="TransactionClassification",
)
COUNTERPARTY_TYPE_DB = postgres_enum(CounterpartyType, name="CounterpartyType")
ALIAS_MATCH_TYPE_DB = postgres_enum(AliasMatchType, name="AliasMatchType")
CATEGORY_TYPE_DB = postgres_enum(CategoryType, name="CategoryType")
RULE_FIELD_DB = postgres_enum(RuleField, name="RuleField")
RULE_OPERATOR_DB = postgres_enum(RuleOperator, name="RuleOperator")
BUDGET_PERIOD_TYPE_DB = postgres_enum(BudgetPeriodType, name="BudgetPeriodType")
BUDGET_ALERT_TYPE_DB = postgres_enum(BudgetAlertType, name="BudgetAlertType")
ASSET_ALIAS_PROVIDER_DB = postgres_enum(AssetAliasProvider, name="AssetAliasProvider")
ASSET_TYPE_DB = postgres_enum(AssetType, name="AssetType")
PRICE_SOURCE_DB = postgres_enum(PriceSource, name="PriceSource")
EXCHANGE_RATE_SOURCE_DB = postgres_enum(ExchangeRateSource, name="ExchangeRateSource")
INVESTMENT_EVENT_TYPE_DB = postgres_enum(InvestmentEventType, name="InvestmentEventType")
INVESTMENT_MOVEMENT_KIND_DB = postgres_enum(
    InvestmentMovementKind,
    name="InvestmentMovementKind",
)
MOVEMENT_DIRECTION_DB = postgres_enum(MovementDirection, name="MovementDirection")
IMPORT_SOURCE_DB = postgres_enum(ImportSource, name="ImportSource")
IMPORT_STATUS_DB = postgres_enum(ImportStatus, name="ImportStatus")
IMPORT_ROW_STATUS_DB = postgres_enum(ImportRowStatus, name="ImportRowStatus")
IMPORT_LOG_LEVEL_DB = postgres_enum(ImportLogLevel, name="ImportLogLevel")
IMPORT_LOG_EVENT_DB = postgres_enum(ImportLogEvent, name="ImportLogEvent")
SNAPSHOT_GRANULARITY_DB = postgres_enum(SnapshotGranularity, name="SnapshotGranularity")
SNAPSHOT_SOURCE_DB = postgres_enum(SnapshotSource, name="SnapshotSource")
