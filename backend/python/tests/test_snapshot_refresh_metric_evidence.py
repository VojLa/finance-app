from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import (
    AccountType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import HoldingPersistenceMovement
from app.modules.portfolio_history_rebuild.models import InvestmentEventRoot, TransactionRoot
from app.modules.snapshot_refresh.metric_evidence import (
    build_complete_historical_metric_evidence,
    build_historical_metric_evidence,
)
from app.modules.snapshots.account_projection import ExpectedAccountSnapshotValuation
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    HistoricalMetricKind,
    SelectedHistoricalRate,
)

_ACCOUNT_ID = "account-1"
_EVENT_AT = datetime(2026, 1, 2, 10, 0)
_AS_OF = datetime(2026, 1, 3, 10, 0)


def _valuation() -> ExpectedAccountSnapshotValuation:
    return ExpectedAccountSnapshotValuation(
        account_id=_ACCOUNT_ID,
        timestamp=_AS_OF,
        granularity=SnapshotGranularity.minute,
        source=SnapshotSource.holdings_recalculation,
        currency="EUR",
        calculation_version=1,
        cash_value=Decimal("0.000000"),
        investment_value=Decimal("0.000000"),
        investment_cost_basis=None,
        liabilities_value=Decimal("0.000000"),
        total_value=Decimal("0.000000"),
        cash_value_by_currency=(),
        investment_value_by_currency=(),
        investment_cost_basis_by_currency=None,
        liabilities_value_by_currency=(),
        exchange_rates=(),
        items=(),
    )


def _movement(
    movement_id: str,
    *,
    kind: InvestmentMovementKind,
    direction: MovementDirection,
    quantity: Decimal,
    currency: str = "USD",
    price_per_unit: Decimal | None = None,
    value_amount: Decimal | None = None,
    value_currency: str | None = None,
) -> HoldingPersistenceMovement:
    return HoldingPersistenceMovement(
        movement_id=movement_id,
        event_id="event-1",
        account_id=_ACCOUNT_ID,
        kind=kind,
        direction=direction,
        quantity=quantity,
        currency=currency,
        asset_id=None,
        listing_id=None,
        listing_asset_id=None,
        source_symbol=None,
        source_asset_type=None,
        price_per_unit=price_per_unit,
        value_amount=value_amount,
        value_currency=value_currency,
    )


def _event(
    *,
    event_id: str = "event-1",
    event_type: InvestmentEventType,
    movements: tuple[HoldingPersistenceMovement, ...],
    source: ImportSource | None = ImportSource.manual,
    realized_pnl: Decimal | None = None,
    realized_pnl_currency: str | None = None,
    event_at: datetime = _EVENT_AT,
) -> InvestmentEventRoot:
    return InvestmentEventRoot(
        event_id=event_id,
        account_id=_ACCOUNT_ID,
        event_type=event_type,
        event_date=event_at,
        movements=tuple(
            movement
            if movement.event_id == event_id
            else HoldingPersistenceMovement(
                movement_id=movement.movement_id,
                event_id=event_id,
                account_id=movement.account_id,
                kind=movement.kind,
                direction=movement.direction,
                quantity=movement.quantity,
                currency=movement.currency,
                asset_id=movement.asset_id,
                listing_id=movement.listing_id,
                listing_asset_id=movement.listing_asset_id,
                source_symbol=movement.source_symbol,
                source_asset_type=movement.source_asset_type,
                price_per_unit=movement.price_per_unit,
                value_amount=movement.value_amount,
                value_currency=movement.value_currency,
                listing_currency=movement.listing_currency,
            )
            for movement in movements
        ),
        source=source,
        realized_pnl=realized_pnl,
        realized_pnl_currency=realized_pnl_currency,
    )


def _rates(
    *evidence_ids: str, rate: Decimal = Decimal("0.8000000000")
) -> tuple[SelectedHistoricalRate, ...]:
    return tuple(
        SelectedHistoricalRate(
            rate_id="usd-eur-event-rate",
            evidence_id=evidence_id,
            base_currency="USD",
            quote_currency="EUR",
            rate=rate,
            timestamp=_EVENT_AT,
        )
        for evidence_id in evidence_ids
    )


def _transaction(
    transaction_id: str,
    amount: str,
    *,
    currency: str = "USD",
    event_at: datetime = _EVENT_AT,
) -> TransactionRoot:
    value = Decimal(amount)
    return TransactionRoot(
        transaction_id=transaction_id,
        account_id=_ACCOUNT_ID,
        timestamp=event_at,
        amount=value,
        currency=currency,
        transaction_type=(TransactionType.income if value > 0 else TransactionType.expense),
        classification=(
            TransactionClassification.real_income
            if value > 0
            else TransactionClassification.real_expense
        ),
        eligible=True,
    )


def test_uses_event_date_fx_and_preserves_native_deposit_evidence() -> None:
    root = _event(
        event_type=InvestmentEventType.cash_deposit,
        movements=(
            _movement(
                "deposit-1",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("10.000000"),
            ),
        ),
    )

    result = build_complete_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(root,),
        as_of=_AS_OF,
        valuation=_valuation(),
        historical_rates=_rates("deposit:deposit-1"),
    )

    assert result.metrics.net_deposits_value == Decimal("8.000000")
    assert result.metrics.net_deposits_by_currency[0].currency == "USD"
    assert result.metrics.net_deposits_by_currency[0].amount == Decimal("10.000000")
    assert result.metrics.selected_historical_rate_ids == ("usd-eur-event-rate",)
    assert result.metrics.consumed_historical_exchange_rates[0].timestamp == _EVENT_AT


def test_materializes_fees_taxes_and_realized_pnl_with_stable_evidence_ids() -> None:
    root = _event(
        event_type=InvestmentEventType.trade,
        movements=(
            _movement(
                "asset-out",
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.outgoing,
                quantity=Decimal("1.000000"),
            ),
            _movement(
                "cash-in",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("12.000000"),
            ),
            _movement(
                "fee-1",
                kind=InvestmentMovementKind.fee,
                direction=MovementDirection.outgoing,
                quantity=Decimal("2.000000"),
            ),
            _movement(
                "tax-1",
                kind=InvestmentMovementKind.tax,
                direction=MovementDirection.outgoing,
                quantity=Decimal("1.000000"),
            ),
        ),
        realized_pnl=Decimal("3.000000"),
        realized_pnl_currency="USD",
    )

    result = build_complete_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(root,),
        as_of=_AS_OF,
        valuation=_valuation(),
        historical_rates=_rates("movement:fee-1", "movement:tax-1", "realized:event-1"),
    )

    assert result.metrics.fees_value == Decimal("1.600000")
    assert result.metrics.taxes_value == Decimal("0.800000")
    assert result.metrics.realized_pnl_value == Decimal("2.400000")
    assert [item.evidence_id for item in result.evidence.historical_evidence] == [
        "movement:fee-1",
        "movement:tax-1",
        "realized:event-1",
    ]
    assert [item.kind for item in result.evidence.historical_evidence] == [
        HistoricalMetricKind.fee,
        HistoricalMetricKind.tax,
        HistoricalMetricKind.realized_pnl,
    ]


def test_fails_closed_when_the_event_date_rate_is_missing() -> None:
    root = _event(
        event_type=InvestmentEventType.cash_deposit,
        movements=(
            _movement(
                "deposit-1",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("10.000000"),
            ),
        ),
    )

    with pytest.raises(AccountSnapshotEvidenceStateError):
        build_complete_historical_metric_evidence(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.broker,
            roots=(root,),
            as_of=_AS_OF,
            valuation=_valuation(),
            historical_rates=(),
        )


def test_ignores_roots_after_the_as_of_timestamp() -> None:
    current = _event(
        event_type=InvestmentEventType.cash_deposit,
        movements=(
            _movement(
                "deposit-now",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("10.000000"),
            ),
        ),
    )
    future = _event(
        event_id="event-2",
        event_type=InvestmentEventType.cash_deposit,
        event_at=datetime(2026, 1, 4, 10, 0),
        movements=(
            _movement(
                "deposit-future",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("7.000000"),
            ),
        ),
    )

    result = build_complete_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(current, future),
        as_of=_AS_OF,
        valuation=_valuation(),
        historical_rates=_rates("deposit:deposit-now"),
    )

    assert result.metrics.net_deposits_value == Decimal("8.000000")
    assert [item.evidence_id for item in result.evidence.historical_evidence] == [
        "deposit:deposit-now"
    ]


def test_retains_legacy_unvalued_transfer_and_anycoin_realized_pnl_flags() -> None:
    transfer = _event(
        event_type=InvestmentEventType.asset_transfer,
        movements=(
            _movement(
                "transfer-asset",
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.incoming,
                quantity=Decimal("1.000000"),
            ),
        ),
    )
    anycoin_sale = _event(
        event_id="event-2",
        event_type=InvestmentEventType.trade,
        source=ImportSource.anycoin,
        movements=(
            _movement(
                "anycoin-asset",
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.outgoing,
                quantity=Decimal("1.000000"),
            ),
            _movement(
                "anycoin-cash",
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("5.000000"),
            ),
        ),
    )

    result = build_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(transfer, anycoin_sale),
        as_of=_AS_OF,
    )

    assert result.has_asset_transfer is True
    assert result.has_missing_anycoin_realized_pnl is True


def test_trading_card_cash_flows_change_only_net_deposits_metric() -> None:
    debit = _transaction("card-debit", "-12.000000")
    cashback_at = _EVENT_AT + timedelta(days=1)
    cashback = _transaction("cashback", "4.000000", event_at=cashback_at)
    rates = (
        SelectedHistoricalRate(
            rate_id="debit-rate",
            evidence_id="transaction:card-debit",
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.8000000000"),
            timestamp=_EVENT_AT,
        ),
        SelectedHistoricalRate(
            rate_id="cashback-rate",
            evidence_id="transaction:cashback",
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.9000000000"),
            timestamp=cashback_at,
        ),
    )

    result = build_complete_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(debit, cashback),
        as_of=_AS_OF,
        valuation=_valuation(),
        historical_rates=rates,
    )

    assert result.metrics.net_deposits_value == Decimal("-6.000000")
    assert result.metrics.net_deposits_by_currency[0].amount == Decimal("-8.000000")
    assert result.metrics.realized_pnl_value == Decimal("0.000000")
    assert result.metrics.fees_value == Decimal("0.000000")
    assert result.metrics.taxes_value == Decimal("0.000000")
    assert [item.evidence_id for item in result.evidence.historical_evidence] == [
        "transaction:card-debit",
        "transaction:cashback",
    ]


def test_ineligible_transaction_does_not_enter_historical_metrics() -> None:
    result = build_historical_metric_evidence(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        roots=(replace(_transaction("review", "-5.000000"), eligible=False),),
        as_of=_AS_OF,
    )

    assert result.historical_evidence == ()
