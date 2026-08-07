from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
    LiabilityBalanceSource,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.modules.liabilities.evidence_service import (
    LiabilityBalanceEvidence as SelectedLiabilityBalanceEvidence,
)
from app.modules.liabilities.evidence_service import (
    LiabilityBalanceEvidenceStateError,
)
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CashBalanceEvidence,
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_repository import (
    AccountSnapshotEvidenceRepository,
    PersistedHoldingEvidence,
)
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    HistoricalMetricEvidence,
    HistoricalMetricKind,
    SelectedHistoricalRate,
    build_financial_metrics,
)

NOW = datetime(2026, 7, 27)
EARLIER = datetime(2026, 7, 26)


def _account(
    account_type: AccountType = AccountType.bank,
    *,
    currency: str = "CZK",
) -> AccountModel:
    return AccountModel(
        id="account-1",
        name="Account",
        type=account_type,
        currency=currency,
        is_archived=False,
        archived_at=None,
        updated_at=NOW,
    )


def _transaction(
    transaction_id: str,
    amount: str,
    transaction_type: TransactionType,
    *,
    currency: str = "CZK",
) -> TransactionModel:
    return TransactionModel(
        id=transaction_id,
        account_id="account-1",
        date=EARLIER,
        booking_date=None,
        amount=Decimal(amount),
        currency=currency,
        reporting_amount=None,
        reporting_currency=None,
        type=transaction_type,
        classification=(
            TransactionClassification.real_income
            if transaction_type is TransactionType.income
            else TransactionClassification.real_expense
        ),
        description=None,
        note=None,
        counterparty=None,
        external_id=None,
        is_reviewed=False,
        archived_at=None,
        deleted_at=None,
        category_id=None,
        import_batch_id=None,
        updated_at=NOW,
    )


def _holding_rows(
    *,
    holding_currency: str = "EUR",
) -> tuple[PersistedHoldingEvidence, ...]:
    asset = AssetModel(
        id="asset-1",
        symbol="ABC",
        isin=None,
        name="ABC",
        asset_type=AssetType.stock,
        currency="EUR",
        updated_at=NOW,
    )
    listing = AssetListingModel(
        id="listing-1",
        asset_id=asset.id,
        symbol="ABC",
        exchange="trading212",
        mic=None,
        currency="EUR",
        country=None,
        provider=PriceSource.broker,
        provider_symbol="ABC",
        is_primary=False,
        updated_at=NOW,
    )
    holding = HoldingModel(
        id="holding-1",
        account_id="account-1",
        asset_id=asset.id,
        listing_id=listing.id,
        symbol="ABC",
        name="ABC",
        asset_type=AssetType.stock,
        quantity=Decimal("2"),
        avg_buy_price=Decimal("10"),
        currency=holding_currency,
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        calculated_at=EARLIER,
        updated_at=EARLIER,
    )
    return (PersistedHoldingEvidence(holding, listing, asset),)


def _price(
    price_id: str,
    value: str,
    timestamp: datetime,
    *,
    currency: str = "EUR",
    source: PriceSource = PriceSource.broker,
) -> PriceSnapshotModel:
    return PriceSnapshotModel(
        id=price_id,
        asset_id="asset-1",
        listing_id="listing-1",
        price=Decimal(value),
        currency=currency,
        source=source,
        timestamp=timestamp,
    )


def _rate(
    rate_id: str,
    value: str,
    timestamp: datetime,
    *,
    base_currency: str = "EUR",
    quote_currency: str = "CZK",
    source: ExchangeRateSource = ExchangeRateSource.cnb,
) -> ExchangeRateModel:
    return ExchangeRateModel(
        id=rate_id,
        from_currency=base_currency,
        to_currency=quote_currency,
        rate=Decimal(value),
        date=timestamp,
        source=source,
    )


def _event(
    event_type: InvestmentEventType = InvestmentEventType.cash_deposit,
) -> InvestmentEventModel:
    return InvestmentEventModel(
        id="event-deposit",
        account_id="account-1",
        type=event_type,
        date=EARLIER,
        source=None,
        external_id=None,
        order_id=None,
        description=None,
        realized_pnl=None,
        realized_pnl_currency=None,
        import_batch_id=None,
        archived_at=None,
        deleted_at=None,
        updated_at=NOW,
    )


def _movement(
    *,
    currency: str = "EUR",
) -> InvestmentMovementModel:
    return InvestmentMovementModel(
        id="movement-deposit",
        event_id="event-deposit",
        account_id="account-1",
        asset_id=None,
        listing_id=None,
        kind=InvestmentMovementKind.cash,
        direction=MovementDirection.incoming,
        quantity=Decimal("10"),
        currency=currency,
        price_per_unit=None,
        value_amount=Decimal("10"),
        value_currency=currency,
        source_symbol=None,
        source_asset_type=None,
        note=None,
        updated_at=NOW,
    )


def _repository(**overrides: object) -> AccountSnapshotEvidenceRepository:
    defaults: dict[str, object] = {
        "load_account": _account(),
        "load_holdings": (),
        "load_active_transactions": (),
        "load_active_events": (),
        "load_active_movements": (),
        "load_price_candidates": (),
        "load_exchange_rate_candidates": (),
    }
    defaults.update(overrides)
    repository = SimpleNamespace()
    for name, value in defaults.items():
        setattr(repository, name, AsyncMock(return_value=value))
    return cast(AccountSnapshotEvidenceRepository, repository)


def _command(**changes: Any) -> BuildAccountSnapshotEvidenceCommand:
    command = BuildAccountSnapshotEvidenceCommand(
        account_id="account-1",
        snapshot_timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
    )
    return replace(command, **changes)


@pytest.mark.asyncio
async def test_omitted_output_currency_is_structurally_equal_to_explicit_account_currency() -> None:
    repository = _repository()
    service = AccountSnapshotEvidenceService(MagicMock(), repository=repository)

    default = await service.build(_command())
    explicit = await service.build(_command(output_currency="CZK"))

    assert default == explicit
    assert default.valuation.currency == "CZK"


@pytest.mark.asyncio
@pytest.mark.parametrize("account_type", [AccountType.broker, AccountType.bank])
async def test_empty_mixed_currency_account_uses_requested_output_without_fx(
    account_type: AccountType,
) -> None:
    repository = _repository(load_account=_account(account_type, currency="USD"))

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command(output_currency="EUR"))

    assert result.valuation.currency == "EUR"
    assert result.valuation.total_value == Decimal(0)
    assert result.selected_snapshot_exchange_rate_ids == ()
    assert result.selected_historical_exchange_rate_ids == ()
    cast(AsyncMock, repository.load_exchange_rate_candidates).assert_awaited_once_with(
        (),
        "CZK",
        through=NOW,
    )


@pytest.mark.asyncio
async def test_empty_rate_repository_request_issues_no_sql() -> None:
    session = MagicMock()
    repository = AccountSnapshotEvidenceRepository(session)

    result = await repository.load_exchange_rate_candidates(
        (),
        "EUR",
        through=NOW,
    )

    assert result == ()
    session.scalars.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("output_currency", ["", " ", "eur", " EUR", "EUR "])
async def test_invalid_explicit_output_currency_fails_before_database_reads(
    output_currency: str,
) -> None:
    repository = _repository()

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command(output_currency=output_currency))

    cast(AsyncMock, repository.load_account).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": " account-1"},
        {"snapshot_timestamp": datetime(2026, 7, 27, 0, 0, 0, 1)},
        {"snapshot_timestamp": datetime(2026, 7, 27, tzinfo=UTC)},
        {"snapshot_timestamp": datetime(2026, 7, 27, 1)},
        {"granularity": cast(SnapshotGranularity, "day")},
        {"source": cast(SnapshotSource, "manual")},
        {"calculation_version": 0},
        {"calculation_version": 2_147_483_648},
        {"calculation_version": cast(int, True)},
    ],
)
async def test_invalid_command_metadata_fails_before_database_reads(
    changes: dict[str, object],
) -> None:
    repository = _repository()

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command(**changes))

    cast(AsyncMock, repository.load_account).assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_runtime_command_fails_before_database_reads() -> None:
    repository = _repository()
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(cast(BuildAccountSnapshotEvidenceCommand, object()))
    cast(AsyncMock, repository.load_account).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "wrong-runtime",
        "wrong-id",
        "archived",
        "contradictory-archive",
        "bad-currency",
        "bad-type",
    ],
)
async def test_malformed_persisted_account_fails_closed(corruption: str) -> None:
    account: object = _account()
    if corruption == "missing":
        account = None
    elif corruption == "wrong-runtime":
        account = SimpleNamespace(id="account-1")
    elif corruption == "wrong-id":
        cast(AccountModel, account).id = "other"
    elif corruption == "archived":
        cast(AccountModel, account).is_archived = True
        cast(AccountModel, account).archived_at = NOW
    elif corruption == "contradictory-archive":
        cast(AccountModel, account).archived_at = NOW
    elif corruption == "bad-currency":
        cast(AccountModel, account).currency = "usd"
    else:
        cast(AccountModel, account).type = cast(AccountType, "unsupported")

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=_repository(load_account=account),
        ).build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
async def test_cash_account_balance_uses_complete_signed_transaction_history(
    account_type: AccountType,
) -> None:
    repository = _repository(
        load_account=_account(account_type),
        load_active_transactions=(
            _transaction("income", "100.000000", TransactionType.income),
            _transaction("expense", "-30.000000", TransactionType.expense),
        ),
    )
    session = MagicMock()

    result = await AccountSnapshotEvidenceService(
        session,
        repository=repository,
    ).build(_command())

    assert result.valuation.cash_value == Decimal("70.000000")
    assert result.valuation.total_value == Decimal("70.000000")
    assert result.valuation.liabilities_value == Decimal(0)
    assert result.valuation.liabilities_value_by_currency == ()
    structural_zero = ExactSnapshotMetric(Decimal(0), ())
    assert result.net_deposits == structural_zero
    assert result.fees == structural_zero
    assert result.taxes == structural_zero
    assert result.realized_pnl == structural_zero
    assert result.unrealized_pnl == structural_zero
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()
    session.begin.assert_not_called()
    session.begin_nested.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transaction_type", "classification", "amount"),
    [
        (TransactionType.income, TransactionClassification.real_income, "100.000000"),
        (TransactionType.expense, TransactionClassification.real_expense, "-10.000000"),
        (
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
            "-5.000000",
        ),
        (
            TransactionType.transfer,
            TransactionClassification.investment_transfer,
            "-5.000000",
        ),
        (
            TransactionType.transfer,
            TransactionClassification.cash_exchange,
            "-5.000000",
        ),
        (
            TransactionType.transfer,
            TransactionClassification.credit_card_payment,
            "-5.000000",
        ),
        (
            TransactionType.transfer,
            TransactionClassification.loan_repayment,
            "-5.000000",
        ),
    ],
)
async def test_cash_transaction_semantics_use_only_structurally_applicable_metrics(
    transaction_type: TransactionType,
    classification: TransactionClassification,
    amount: str,
) -> None:
    transaction = _transaction("transaction", amount, transaction_type)
    transaction.classification = classification
    transaction.description = "external deposit withdrawal bank fee tax"
    transaction.category_id = "category-that-must-not-classify-the-row"
    repository = _repository(load_active_transactions=(transaction,))

    with patch("app.modules.snapshots.evidence_service.build_financial_metrics") as metrics:
        first = await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())
        second = await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())

    assert first == second
    structural_zero = ExactSnapshotMetric(Decimal(0), ())
    assert first.net_deposits == structural_zero
    assert first.fees == structural_zero
    assert first.taxes == structural_zero
    assert first.realized_pnl == structural_zero
    assert first.unrealized_pnl == structural_zero
    metrics.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.exchange, AccountType.crypto_wallet],
)
async def test_investment_account_selects_snapshot_and_event_date_fx_separately(
    account_type: AccountType,
) -> None:
    repository = _repository(
        load_account=_account(account_type),
        load_holdings=_holding_rows(),
        load_active_events=(_event(),),
        load_active_movements=(_movement(),),
        load_price_candidates=(
            _price("old-price", "14", EARLIER),
            _price("selected-price", "15", NOW),
        ),
        load_exchange_rate_candidates=(
            _rate("event-rate", "20", EARLIER),
            _rate("snapshot-rate", "25", NOW),
        ),
    )

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command())

    assert result.valuation.investment_value == Decimal("750.000000")
    assert result.valuation.investment_cost_basis == Decimal("500.000000")
    assert result.valuation.cash_value == Decimal("250.000000")
    assert result.valuation.liabilities_value == Decimal(0)
    assert result.valuation.liabilities_value_by_currency == ()
    assert result.net_deposits == ExactSnapshotMetric(
        Decimal("200.000000"),
        (CurrencyAmount("EUR", Decimal("10.000000")),),
    )
    assert result.unrealized_pnl == ExactSnapshotMetric(
        Decimal("250.000000"),
        (CurrencyAmount("EUR", Decimal("10.000000")),),
    )
    assert result.selected_price_ids == ("selected-price",)
    assert result.selected_snapshot_exchange_rate_ids == ("snapshot-rate",)
    assert result.selected_historical_exchange_rate_ids == ("event-rate",)


@pytest.mark.asyncio
async def test_mixed_currency_investment_selects_only_direct_czk_pivot_legs() -> None:
    repository = _repository(
        load_account=_account(AccountType.broker, currency="USD"),
        load_holdings=_holding_rows(holding_currency="USD"),
        load_active_events=(_event(InvestmentEventType.interest),),
        load_active_movements=(_movement(currency="CHF"),),
        load_price_candidates=(_price("price-gbp", "15", NOW, currency="GBP"),),
        load_exchange_rate_candidates=(
            _rate(
                "rate-usd",
                "18",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "rate-chf",
                "21",
                NOW,
                base_currency="CHF",
                quote_currency="CZK",
            ),
            _rate(
                "rate-gbp",
                "24",
                NOW,
                base_currency="GBP",
                quote_currency="CZK",
            ),
            _rate(
                "rate-eur",
                "20",
                NOW,
                base_currency="EUR",
                quote_currency="CZK",
            ),
        ),
    )

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command(output_currency="EUR"))

    assert result.valuation.currency == "EUR"
    assert result.valuation.investment_value == Decimal("36.000000")
    assert result.valuation.investment_cost_basis == Decimal("18.000000")
    assert result.valuation.cash_value == Decimal("10.500000")
    assert result.valuation.total_value == Decimal("46.500000")
    assert result.valuation.cash_value_by_currency == (CurrencyAmount("CHF", Decimal("10.000000")),)
    assert result.valuation.investment_value_by_currency == (
        CurrencyAmount("GBP", Decimal("30.0000000000")),
    )
    assert result.valuation.investment_cost_basis_by_currency == (
        CurrencyAmount("USD", Decimal("20.0000000000")),
    )
    assert result.selected_snapshot_exchange_rate_ids == (
        "rate-chf",
        "rate-eur",
        "rate-gbp",
        "rate-usd",
    )
    assert result.selected_historical_exchange_rate_ids == ()
    cast(AsyncMock, repository.load_exchange_rate_candidates).assert_awaited_once_with(
        ("CHF", "EUR", "GBP", "USD"),
        "CZK",
        through=NOW,
    )


@pytest.mark.asyncio
async def test_account_currency_pivot_rejects_non_cnb_observation() -> None:
    repository = _repository(
        load_account=_account(AccountType.broker, currency="EUR"),
        load_holdings=_holding_rows(holding_currency="EUR"),
        load_price_candidates=(_price("price-usd", "15", NOW, currency="USD"),),
        load_exchange_rate_candidates=(
            _rate("eur-czk", "20", NOW, base_currency="EUR"),
            _rate(
                "usd-czk",
                "18",
                NOW,
                base_currency="USD",
                source=ExchangeRateSource.ecb,
            ),
        ),
    )

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command(output_currency="EUR"))


@pytest.mark.asyncio
async def test_explicit_output_currency_keeps_snapshot_and_event_time_rates_separate() -> None:
    repository = _repository(
        load_account=_account(AccountType.broker, currency="USD"),
        load_holdings=_holding_rows(holding_currency="USD"),
        load_active_events=(_event(),),
        load_active_movements=(_movement(currency="USD"),),
        load_price_candidates=(_price("price-usd", "15", NOW, currency="USD"),),
        load_exchange_rate_candidates=(
            _rate(
                "event-usd",
                "16",
                EARLIER,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "snapshot-usd",
                "18",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "event-eur",
                "20",
                EARLIER,
                base_currency="EUR",
                quote_currency="CZK",
            ),
            _rate(
                "snapshot-eur",
                "20",
                NOW,
                base_currency="EUR",
                quote_currency="CZK",
            ),
        ),
    )

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command(output_currency="EUR"))

    assert result.valuation.investment_value == Decimal("27.000000")
    assert result.valuation.investment_cost_basis == Decimal("18.000000")
    assert result.valuation.cash_value == Decimal("9.000000")
    assert result.net_deposits == ExactSnapshotMetric(
        Decimal("8.000000"),
        (CurrencyAmount("USD", Decimal("10.000000")),),
    )
    assert result.selected_snapshot_exchange_rate_ids == (
        "snapshot-eur",
        "snapshot-usd",
    )
    assert result.selected_historical_exchange_rate_ids == (
        "event-eur",
        "event-usd",
    )


@pytest.mark.asyncio
async def test_mixed_currency_cash_preserves_native_breakdown_and_unsupported_metrics() -> None:
    repository = _repository(
        load_account=_account(AccountType.bank, currency="USD"),
        load_active_transactions=(
            _transaction("usd", "100.000000", TransactionType.income, currency="USD"),
            _transaction("eur", "20.000000", TransactionType.income, currency="EUR"),
        ),
        load_exchange_rate_candidates=(
            _rate(
                "usd-czk",
                "18",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "eur-czk",
                "20",
                NOW,
                base_currency="EUR",
                quote_currency="CZK",
            ),
        ),
    )

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command(output_currency="EUR"))

    assert result.valuation.currency == "EUR"
    assert result.valuation.cash_value == Decimal("110.000000")
    assert result.valuation.cash_value_by_currency == (
        CurrencyAmount("EUR", Decimal("20.000000")),
        CurrencyAmount("USD", Decimal("100.000000")),
    )
    assert result.selected_snapshot_exchange_rate_ids == ("eur-czk", "usd-czk")
    assert result.selected_historical_exchange_rate_ids == ()
    structural_zero = ExactSnapshotMetric(Decimal(0), ())
    assert result.net_deposits == structural_zero
    assert result.realized_pnl == structural_zero
    assert result.fees == structural_zero
    assert result.taxes == structural_zero


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rates",
    [
        (),
        (
            _rate(
                "reverse",
                "1.1",
                NOW,
                base_currency="EUR",
                quote_currency="USD",
            ),
        ),
        (
            _rate(
                "usd-czk",
                "20",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "czk-eur",
                "0.04",
                NOW,
                base_currency="CZK",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "unrelated",
                "1.2",
                NOW,
                base_currency="GBP",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "future",
                "0.9",
                datetime(2026, 7, 28),
                base_currency="USD",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "zero",
                "0",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "bad-source",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
                source=cast(ExchangeRateSource, "unknown"),
            ),
        ),
        (
            _rate(
                "bad-time",
                "0.9",
                datetime(2026, 7, 27, 0, 0, 0, 1),
                base_currency="USD",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "duplicate",
                "0.8",
                EARLIER,
                base_currency="USD",
                quote_currency="EUR",
            ),
            _rate(
                "duplicate",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "ecb",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
            ),
            _rate(
                "manual",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
                source=ExchangeRateSource.manual,
            ),
        ),
    ],
)
async def test_direct_persisted_rate_failure_matrix(
    rates: tuple[ExchangeRateModel, ...],
) -> None:
    repository = _repository(
        load_account=_account(AccountType.bank, currency="USD"),
        load_active_transactions=(
            _transaction("usd", "100.000000", TransactionType.income, currency="USD"),
        ),
        load_exchange_rate_candidates=rates,
    )

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command(output_currency="EUR"))


@pytest.mark.asyncio
async def test_future_price_is_ignored() -> None:
    future = datetime(2026, 7, 28)
    repository = _repository(
        load_account=_account(AccountType.broker, currency="EUR"),
        load_holdings=_holding_rows(),
        load_price_candidates=(
            _price("future", "99", future),
            _price("eligible", "15", EARLIER),
        ),
    )
    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
    ).build(_command())
    assert result.selected_price_ids == ("eligible",)


@pytest.mark.asyncio
async def test_same_timestamp_price_ambiguity_fails_closed() -> None:
    repository = _repository(
        load_account=_account(AccountType.broker, currency="EUR"),
        load_holdings=_holding_rows(),
        load_price_candidates=(
            _price("broker", "15", NOW),
            _price("manual", "15", NOW, source=PriceSource.manual),
        ),
    )
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())


@pytest.mark.asyncio
async def test_same_timestamp_fx_ambiguity_fails_closed() -> None:
    repository = _repository(
        load_account=_account(AccountType.broker),
        load_holdings=_holding_rows(),
        load_price_candidates=(_price("price", "15", NOW),),
        load_exchange_rate_candidates=(
            _rate("ecb", "25", NOW),
            _rate("manual", "25", NOW, source=ExchangeRateSource.manual),
        ),
    )
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
async def test_liability_accounts_use_selected_canonical_balance_once(
    account_type: AccountType,
) -> None:
    repository = _repository(load_account=_account(account_type))
    selector = SimpleNamespace(
        select=AsyncMock(
            return_value=SelectedLiabilityBalanceEvidence(
                balance_id="liability-balance-1",
                account_id="account-1",
                effective_at=EARLIER,
                currency="CZK",
                outstanding_principal=Decimal("100.000000"),
                accrued_interest=Decimal("10.000000"),
                fees_outstanding=Decimal("5.000000"),
                total_outstanding=Decimal("115.000000"),
                source=LiabilityBalanceSource.statement,
            )
        )
    )
    session = MagicMock()
    result = await AccountSnapshotEvidenceService(
        session,
        repository=repository,
        liability_evidence_service=selector,
    ).build(_command())

    selector.select.assert_awaited_once()
    assert result.valuation.liabilities_value == Decimal("115.000000")
    assert result.valuation.total_value == Decimal("-115.000000")
    assert result.valuation.items == ()
    assert result.net_deposits == ExactSnapshotMetric(Decimal(0), ())
    assert result.realized_pnl == ExactSnapshotMetric(Decimal(0), ())
    assert result.unrealized_pnl == ExactSnapshotMetric(Decimal(0), ())
    assert result.fees == ExactSnapshotMetric(Decimal(0), ())
    assert result.taxes == ExactSnapshotMetric(Decimal(0), ())
    assert result.selected_liability_balance_id == "liability-balance-1"
    assert result.selected_liability_effective_at == EARLIER
    assert result.selected_liability_source is LiabilityBalanceSource.statement
    cast(AsyncMock, repository.load_holdings).assert_not_awaited()
    cast(AsyncMock, repository.load_active_transactions).assert_not_awaited()
    cast(AsyncMock, repository.load_active_events).assert_not_awaited()
    cast(AsyncMock, repository.load_active_movements).assert_not_awaited()
    cast(AsyncMock, repository.load_price_candidates).assert_not_awaited()
    cast(AsyncMock, repository.load_exchange_rate_candidates).assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()


def _selected_liability(
    *,
    currency: str = "USD",
) -> SelectedLiabilityBalanceEvidence:
    return SelectedLiabilityBalanceEvidence(
        balance_id="liability-balance-1",
        account_id="account-1",
        effective_at=EARLIER,
        currency=currency,
        outstanding_principal=Decimal("100.000000"),
        accrued_interest=Decimal("10.000000"),
        fees_outstanding=Decimal("5.000000"),
        total_outstanding=Decimal("115.000000"),
        source=LiabilityBalanceSource.statement,
    )


@pytest.mark.asyncio
async def test_mixed_currency_liability_selects_and_audits_czk_pivot_legs() -> None:
    repository = _repository(
        load_account=_account(AccountType.loan, currency="USD"),
        load_exchange_rate_candidates=(
            _rate(
                "usd-czk",
                "18",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "eur-czk",
                "20",
                NOW,
                base_currency="EUR",
                quote_currency="CZK",
            ),
        ),
    )
    selector = SimpleNamespace(select=AsyncMock(return_value=_selected_liability()))

    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=repository,
        liability_evidence_service=selector,
    ).build(_command(output_currency="EUR"))

    assert result.valuation.currency == "EUR"
    assert result.valuation.liabilities_value == Decimal("103.500000")
    assert result.valuation.total_value == Decimal("-103.500000")
    assert result.valuation.liabilities_value_by_currency == (
        CurrencyAmount("USD", Decimal("115.000000")),
    )
    assert result.selected_snapshot_exchange_rate_ids == ("eur-czk", "usd-czk")
    assert result.selected_historical_exchange_rate_ids == ()
    assert result.selected_liability_balance_id == "liability-balance-1"
    assert result.selected_liability_effective_at == EARLIER
    assert result.selected_liability_source is LiabilityBalanceSource.statement


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rates",
    [
        (),
        (
            _rate(
                "reverse",
                "1.1",
                NOW,
                base_currency="EUR",
                quote_currency="USD",
            ),
        ),
        (
            _rate(
                "usd-czk",
                "20",
                NOW,
                base_currency="USD",
                quote_currency="CZK",
            ),
            _rate(
                "czk-eur",
                "0.04",
                NOW,
                base_currency="CZK",
                quote_currency="EUR",
            ),
        ),
        (
            _rate(
                "ecb",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
            ),
            _rate(
                "manual",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
                source=ExchangeRateSource.manual,
            ),
        ),
    ],
)
async def test_mixed_currency_liability_rate_failure_matrix(
    rates: tuple[ExchangeRateModel, ...],
) -> None:
    repository = _repository(
        load_account=_account(AccountType.loan, currency="USD"),
        load_exchange_rate_candidates=rates,
    )
    selector = SimpleNamespace(select=AsyncMock(return_value=_selected_liability()))

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
            liability_evidence_service=selector,
        ).build(_command(output_currency="EUR"))


@pytest.mark.asyncio
async def test_selected_liability_currency_must_match_persisted_account_currency() -> None:
    repository = _repository(
        load_account=_account(AccountType.loan, currency="USD"),
        load_exchange_rate_candidates=(
            _rate(
                "usd-eur",
                "0.9",
                NOW,
                base_currency="USD",
                quote_currency="EUR",
            ),
        ),
    )
    selector = SimpleNamespace(select=AsyncMock(return_value=_selected_liability(currency="GBP")))

    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
            liability_evidence_service=selector,
        ).build(_command(output_currency="EUR"))


@pytest.mark.asyncio
async def test_missing_liability_evidence_maps_to_generic_snapshot_error() -> None:
    repository = _repository(load_account=_account(AccountType.loan))
    selector = SimpleNamespace(select=AsyncMock(side_effect=LiabilityBalanceEvidenceStateError()))

    with pytest.raises(
        AccountSnapshotEvidenceStateError,
        match=r"Persisted evidence cannot produce a complete account snapshot\.",
    ) as raised:
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
            liability_evidence_service=selector,
        ).build(_command())

    selector.select.assert_awaited_once()
    cast(AsyncMock, repository.load_holdings).assert_not_awaited()
    assert isinstance(raised.value.__cause__, LiabilityBalanceEvidenceStateError)


@pytest.mark.asyncio
async def test_projection_error_maps_with_cause_and_database_errors_propagate() -> None:
    repository = _repository()
    projection_error = AccountSnapshotProjectionStateError()
    with (
        patch(
            "app.modules.snapshots.evidence_service.build_account_snapshot_projection",
            side_effect=projection_error,
        ),
        pytest.raises(AccountSnapshotEvidenceStateError) as raised,
    ):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())
    assert raised.value.__cause__ is projection_error

    database_error = SQLAlchemyError("database unavailable")
    repository = _repository()
    cast(AsyncMock, repository.load_account).side_effect = database_error
    with pytest.raises(SQLAlchemyError) as database_raised:
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())
    assert database_raised.value is database_error

    programming_error = RuntimeError("unexpected programming error")
    repository = _repository()
    cast(AsyncMock, repository.load_account).side_effect = programming_error
    with pytest.raises(RuntimeError) as programming_raised:
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())
    assert programming_raised.value is programming_error


@pytest.mark.asyncio
async def test_asset_transfer_fails_when_externality_is_not_persisted() -> None:
    event = _event()
    event.type = InvestmentEventType.asset_transfer
    repository = _repository(
        load_account=_account(AccountType.broker, currency="EUR"),
        load_active_events=(event,),
        load_active_movements=(_movement(),),
    )
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=repository,
        ).build(_command())


def _empty_valuation() -> ExpectedAccountSnapshotValuation:
    return build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-1",
            account_type=AccountType.bank,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=NOW,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(),
            cash_balances=(
                CashBalanceEvidence(
                    balance_id="cash",
                    account_id="account-1",
                    currency="CZK",
                    amount=Decimal("1"),
                    timestamp=NOW,
                ),
            ),
            liabilities=(),
        )
    )


def test_financial_metrics_use_signed_flows_and_positive_expense_magnitudes() -> None:
    result = build_financial_metrics(
        valuation=_empty_valuation(),
        historical_evidence=(
            HistoricalMetricEvidence(
                "deposit",
                EARLIER,
                HistoricalMetricKind.net_deposit,
                "EUR",
                Decimal("10"),
            ),
            HistoricalMetricEvidence(
                "withdrawal",
                EARLIER,
                HistoricalMetricKind.net_deposit,
                "CZK",
                Decimal("-50"),
            ),
            HistoricalMetricEvidence(
                "pnl",
                EARLIER,
                HistoricalMetricKind.realized_pnl,
                "CZK",
                Decimal("-3"),
            ),
            HistoricalMetricEvidence(
                "fee",
                EARLIER,
                HistoricalMetricKind.fee,
                "CZK",
                Decimal("2"),
            ),
            HistoricalMetricEvidence(
                "tax",
                EARLIER,
                HistoricalMetricKind.tax,
                "CZK",
                Decimal("1"),
            ),
        ),
        historical_rates=(
            SelectedHistoricalRate(
                "rate",
                "deposit",
                "EUR",
                "CZK",
                Decimal("20"),
                EARLIER,
            ),
        ),
    )
    assert result.net_deposits_value == Decimal("150.000000")
    assert result.realized_pnl_value == Decimal("-3.000000")
    assert result.fees_value == Decimal("2.000000")
    assert result.taxes_value == Decimal("1.000000")


def test_financial_metrics_reject_missing_wrong_or_unused_rate() -> None:
    evidence = (
        HistoricalMetricEvidence(
            "deposit",
            EARLIER,
            HistoricalMetricKind.net_deposit,
            "EUR",
            Decimal("10"),
        ),
    )
    with pytest.raises(AccountSnapshotEvidenceStateError):
        build_financial_metrics(
            valuation=_empty_valuation(),
            historical_evidence=evidence,
            historical_rates=(),
        )
    with pytest.raises(AccountSnapshotEvidenceStateError):
        build_financial_metrics(
            valuation=_empty_valuation(),
            historical_evidence=evidence,
            historical_rates=(
                SelectedHistoricalRate(
                    "rate",
                    "deposit",
                    "USD",
                    "CZK",
                    Decimal("20"),
                    EARLIER,
                ),
            ),
        )


def test_financial_metrics_reject_negative_fee_and_float() -> None:
    for amount in (Decimal("-1"), 1.0):
        with pytest.raises(AccountSnapshotEvidenceStateError):
            build_financial_metrics(
                valuation=_empty_valuation(),
                historical_evidence=(
                    HistoricalMetricEvidence(
                        "fee",
                        EARLIER,
                        HistoricalMetricKind.fee,
                        "CZK",
                        cast(Decimal, amount),
                    ),
                ),
                historical_rates=(),
            )


def test_complete_result_is_frozen() -> None:
    command = _command(output_currency="EUR")
    with pytest.raises(FrozenInstanceError):
        cast(Any, command).output_currency = "USD"

    result = CompleteAccountSnapshotEvidence(
        valuation=_empty_valuation(),
        net_deposits=ExactSnapshotMetric(Decimal(0), ()),
        realized_pnl=ExactSnapshotMetric(Decimal(0), ()),
        unrealized_pnl=ExactSnapshotMetric(Decimal(0), ()),
        fees=ExactSnapshotMetric(Decimal(0), ()),
        taxes=ExactSnapshotMetric(Decimal(0), ()),
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(),
        selected_historical_exchange_rate_ids=(),
    )
    field_name = "net_deposits"
    with pytest.raises(FrozenInstanceError):
        setattr(result, field_name, ExactSnapshotMetric(Decimal(1), ()))
    assert not any(
        isinstance(value, (AccountModel, ExchangeRateModel))
        for value in (
            result.valuation,
            result.net_deposits,
            result.realized_pnl,
            result.unrealized_pnl,
            result.fees,
            result.taxes,
        )
    )


def test_financial_metric_input_is_not_mutated_and_is_deterministic() -> None:
    evidence = (
        HistoricalMetricEvidence(
            "b",
            EARLIER,
            HistoricalMetricKind.net_deposit,
            "CZK",
            Decimal("2"),
        ),
        HistoricalMetricEvidence(
            "a",
            EARLIER,
            HistoricalMetricKind.net_deposit,
            "CZK",
            Decimal("1"),
        ),
    )
    original = tuple(replace(item) for item in evidence)
    first = build_financial_metrics(
        valuation=_empty_valuation(),
        historical_evidence=evidence,
        historical_rates=(),
    )
    second = build_financial_metrics(
        valuation=_empty_valuation(),
        historical_evidence=tuple(reversed(evidence)),
        historical_rates=(),
    )
    assert first == second
    assert evidence == original
