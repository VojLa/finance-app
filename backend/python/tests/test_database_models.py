from sqlalchemy import Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM

from app.db import models as database_models  # noqa: F401
from app.db.base import Base
from app.db.models import MovementDirection

EXPECTED_TABLES = {
    "Account",
    "AccountInvite",
    "AccountMember",
    "AccountSnapshot",
    "AccountSnapshotItem",
    "Asset",
    "AssetAlias",
    "AssetListing",
    "Budget",
    "BudgetAccount",
    "BudgetAlert",
    "BudgetItem",
    "BudgetItemCategory",
    "Category",
    "CategoryRule",
    "Counterparty",
    "CounterpartyAlias",
    "ExchangeRate",
    "Holding",
    "ImportBatch",
    "ImportLog",
    "ImportRow",
    "InvestmentEvent",
    "InvestmentMovement",
    "NetWorthSnapshot",
    "PriceSnapshot",
    "Transaction",
    "TransactionPair",
    "TransactionSplit",
    "User",
}

EXPECTED_ENUMS = {
    "AccountInviteStatus": ["pending", "accepted", "revoked", "expired"],
    "AccountMemberRole": ["owner", "admin", "viewer", "editor"],
    "AccountRelationType": [
        "owner",
        "joint_owner",
        "manager",
        "beneficiary",
        "collaborator",
    ],
    "AccountType": [
        "bank",
        "cash",
        "savings",
        "broker",
        "exchange",
        "crypto_wallet",
        "credit_card",
        "loan",
        "mortgage",
    ],
    "AliasMatchType": ["exact", "contains", "starts_with", "ends_with"],
    "AssetAliasProvider": ["coingecko", "yahoo_finance", "stooq", "broker", "exchange"],
    "AssetType": ["stock", "etf", "crypto", "commodity", "cash", "bond", "other"],
    "BudgetAlertType": ["approaching_limit", "exceeded", "reset"],
    "BudgetPeriodType": ["monthly", "weekly", "yearly", "custom"],
    "CategoryType": ["expense", "income", "both"],
    "CounterpartyType": [
        "merchant",
        "family",
        "partner",
        "friend",
        "employer",
        "broker",
        "exchange",
        "bank",
        "service_provider",
        "other",
    ],
    "ExchangeRateSource": [
        "cnb",
        "ecb",
        "manual",
        "broker",
        "exchange",
        "yahoo_finance",
    ],
    "ImportLogEvent": [
        "started",
        "parse_error",
        "validation_failed",
        "dedup_skipped",
        "holdings_recalculated",
        "snapshots_recalculated",
        "snapshot_validation_failed",
        "completed",
        "failed",
    ],
    "ImportLogLevel": ["info", "warning", "error"],
    "ImportRowStatus": [
        "pending",
        "imported",
        "skipped",
        "duplicate",
        "failed",
        "needs_review",
    ],
    "ImportSource": ["raiffeisenbank", "trading212", "anycoin", "manual"],
    "ImportStatus": [
        "pending",
        "processing",
        "completed",
        "failed",
        "partially_completed",
        "cancelled",
    ],
    "InvestmentEventType": [
        "trade",
        "cash_deposit",
        "cash_withdrawal",
        "dividend",
        "interest",
        "currency_conversion",
        "asset_transfer",
        "fee",
        "staking_reward",
        "airdrop",
        "adjustment",
    ],
    "InvestmentMovementKind": ["asset", "cash", "fee", "tax"],
    "MovementDirection": ["in", "out"],
    "PriceSource": [
        "coingecko",
        "yahoo_finance",
        "stooq",
        "manual",
        "broker",
        "exchange",
    ],
    "RuleField": ["description", "counterparty"],
    "RuleOperator": [
        "contains",
        "equals",
        "starts_with",
        "ends_with",
        "greater_than",
        "less_than",
    ],
    "SnapshotGranularity": ["minute", "hour", "day", "week", "month"],
    "SnapshotSource": [
        "import_event",
        "price_refresh",
        "holdings_recalculation",
        "scheduled",
        "manual_recalculation",
    ],
    "TransactionClassification": [
        "real_income",
        "real_expense",
        "internal_transfer",
        "investment_transfer",
        "loan_given",
        "loan_received",
        "loan_repayment",
        "refund",
        "cash_exchange",
        "credit_card_payment",
        "ignored",
        "needs_review",
    ],
    "TransactionType": ["income", "expense", "transfer"],
}


def mapped_enums() -> dict[str, ENUM]:
    enums: dict[str, ENUM] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, ENUM) and column.type.name is not None:
                enums[column.type.name] = column.type
    return enums


def test_complete_schema_mirror_maps_all_tables() -> None:
    tables = {table.name: table for table in Base.metadata.tables.values()}

    assert set(tables) == EXPECTED_TABLES
    assert len(tables) == 30
    assert all(table.schema == "public" for table in tables.values())
    assert all(
        [column.name for column in table.primary_key.columns] == ["id"] for table in tables.values()
    )


def test_account_notes_column_is_nullable_text() -> None:
    column = Base.metadata.tables["public.Account"].c.notes

    assert isinstance(column.type, Text)
    assert column.nullable is True
    assert column.server_default is None


def test_all_foreign_keys_target_mapped_tables() -> None:
    mapped_keys = set(Base.metadata.tables)

    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.fullname in mapped_keys


def test_complete_schema_mirror_reuses_all_postgresql_enums() -> None:
    enums = mapped_enums()

    assert len(enums) == 27
    assert {name: enum.enums for name, enum in enums.items()} == EXPECTED_ENUMS
    assert all(enum.create_type is False for enum in enums.values())


def test_financial_numeric_precision_matches_postgresql_schema() -> None:
    expected = {
        ("Holding", "quantity"): (28, 10),
        ("Holding", "avgBuyPrice"): (28, 10),
        ("ExchangeRate", "rate"): (18, 8),
        ("BudgetAlert", "threshold"): (5, 4),
        ("AccountSnapshotItem", "allocationPct"): (8, 4),
        ("AccountSnapshotItem", "value"): (18, 6),
        ("InvestmentMovement", "pricePerUnit"): (28, 10),
    }

    for (table_name, column_name), precision in expected.items():
        column_type = Base.metadata.tables[f"public.{table_name}"].c[column_name].type
        assert isinstance(column_type, Numeric)
        assert (column_type.precision, column_type.scale) == precision


def test_python_safe_enum_names_preserve_database_values() -> None:
    assert MovementDirection.incoming.value == "in"
    assert MovementDirection.outgoing.value == "out"
