from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
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
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    CashBalanceEvidence,
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
) -> TransactionModel:
    return TransactionModel(
        id=transaction_id,
        account_id="account-1",
        date=EARLIER,
        booking_date=None,
        amount=Decimal(amount),
        currency="CZK",
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


def _holding_rows() -> tuple[PersistedHoldingEvidence, ...]:
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
        currency="EUR",
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
    source: PriceSource = PriceSource.broker,
) -> PriceSnapshotModel:
    return PriceSnapshotModel(
        id=price_id,
        asset_id="asset-1",
        listing_id="listing-1",
        price=Decimal(value),
        currency="EUR",
        source=source,
        timestamp=timestamp,
    )


def _rate(
    rate_id: str,
    value: str,
    timestamp: datetime,
    *,
    source: ExchangeRateSource = ExchangeRateSource.ecb,
) -> ExchangeRateModel:
    return ExchangeRateModel(
        id=rate_id,
        from_currency="EUR",
        to_currency="CZK",
        rate=Decimal(value),
        date=timestamp,
        source=source,
    )


def _event() -> InvestmentEventModel:
    return InvestmentEventModel(
        id="event-deposit",
        account_id="account-1",
        type=InvestmentEventType.cash_deposit,
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


def _movement() -> InvestmentMovementModel:
    return InvestmentMovementModel(
        id="movement-deposit",
        event_id="event-deposit",
        account_id="account-1",
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


def _command() -> BuildAccountSnapshotEvidenceCommand:
    return BuildAccountSnapshotEvidenceCommand(
        account_id="account-1",
        snapshot_timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
    )


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
    assert result.net_deposits_value == 0
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()
    session.begin.assert_not_called()
    session.begin_nested.assert_not_called()


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
    assert result.net_deposits_value == Decimal("200.000000")
    assert result.unrealized_pnl_value == Decimal("250.000000")
    assert result.selected_price_ids == ("selected-price",)
    assert result.selected_snapshot_exchange_rate_ids == ("snapshot-rate",)
    assert result.selected_historical_exchange_rate_ids == ("event-rate",)


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
async def test_liability_accounts_fail_without_complete_balance_evidence(
    account_type: AccountType,
) -> None:
    negative_one = _transaction("negative-one", "-100.000000", TransactionType.expense)
    negative_one.description = "Outstanding liability"
    negative_one.category_id = "liability-category"
    negative_two = _transaction("negative-two", "-50.000000", TransactionType.expense)
    negative_two.description = account_type.value
    repository = _repository(
        load_account=_account(account_type),
        load_active_transactions=(negative_one, negative_two),
    )
    session = MagicMock()
    with (
        patch(
            "app.modules.snapshots.evidence_service.build_account_snapshot_projection"
        ) as projection,
        patch("app.modules.snapshots.evidence_service.build_financial_metrics") as metrics,
    ):
        for _ in range(2):
            with pytest.raises(
                AccountSnapshotEvidenceStateError,
                match=r"Persisted evidence cannot produce a complete account snapshot\.",
            ):
                await AccountSnapshotEvidenceService(
                    session,
                    repository=repository,
                ).build(_command())

    projection.assert_not_called()
    metrics.assert_not_called()
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
    result = CompleteAccountSnapshotEvidence(
        valuation=_empty_valuation(),
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=Decimal(0),
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
        net_deposits_by_currency=(),
        realized_pnl_by_currency=(),
        unrealized_pnl_by_currency=(),
        fees_by_currency=(),
        taxes_by_currency=(),
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(),
        selected_historical_exchange_rate_ids=(),
    )
    field_name = "net_deposits_value"
    with pytest.raises(FrozenInstanceError):
        setattr(result, field_name, Decimal(1))


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
