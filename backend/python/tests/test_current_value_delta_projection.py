from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models.enums import (
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    TransactionClassification,
    TransactionType,
)
from app.modules.current_value.delta_projection import (
    CurrentDeltaProjectionError,
    CurrentInvestmentEvent,
    CurrentTransaction,
    apply_cash_transactions,
    apply_investment_cash_transactions,
    apply_investment_events,
)
from app.modules.holdings.persistence_projection import (
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
)
from app.modules.portfolio_snapshot.models import (
    AssetType as PortfolioAssetType,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioCurrencyAmount,
    PortfolioPositionView,
)

AT = datetime(2038, 5, 6, 12)


def _amount(currency: str, amount: str) -> PortfolioCurrencyAmount:
    return PortfolioCurrencyAmount(currency=currency, amount=Decimal(amount))


def _position(quantity: str = "2.0000000000") -> PortfolioPositionView:
    return PortfolioPositionView(
        listing_id="listing-1",
        asset_id="asset-1",
        symbol="AAA",
        name="Asset",
        asset_type=PortfolioAssetType.stock,
        quantity=Decimal(quantity),
        price_per_unit=Decimal("30.0000000000"),
        price_currency="USD",
        price_timestamp=AT,
        value=Decimal("60.000000"),
        value_currency="CZK",
        cost_basis=Decimal("40.0000000000"),
        cost_currency="CZK",
        unrealized_pnl=Decimal("20.0000000000"),
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal("60.0000000000"),
        native_value_currency="USD",
        native_cost_basis=Decimal("40.0000000000"),
        native_cost_currency="USD",
        native_cost_basis_by_currency=(PortfolioCurrencyAmount("USD", Decimal("40.0000000000")),),
        average_buy_price=Decimal("20.0000000000"),
        average_buy_price_currency="USD",
    )


def _movement(
    movement_id: str,
    *,
    kind: InvestmentMovementKind,
    direction: MovementDirection,
    quantity: str,
) -> HoldingPersistenceMovement:
    asset = kind is InvestmentMovementKind.asset
    return HoldingPersistenceMovement(
        movement_id=movement_id,
        event_id="event-1",
        account_id="account-1",
        kind=kind,
        direction=direction,
        quantity=Decimal(quantity),
        currency="AAA" if asset else "USD",
        asset_id="asset-1" if asset else None,
        listing_id="listing-1" if asset else None,
        listing_asset_id="asset-1" if asset else None,
        source_symbol="AAA" if asset else None,
        source_asset_type=AssetType.stock if asset else None,
        price_per_unit=Decimal("30.0000000000") if asset else None,
        value_amount=(Decimal(quantity) * Decimal("30.0000000000") if asset else Decimal(quantity)),
        value_currency="USD",
        listing_currency="USD" if asset else None,
    )


def test_cash_delta_uses_only_forward_signed_transactions() -> None:
    result = apply_cash_transactions(
        account_id="account-1",
        baseline=(_amount("EUR", "10.000000"),),
        transactions=(
            CurrentTransaction(
                transaction_id="income",
                account_id="account-1",
                timestamp=AT,
                amount=Decimal("5.000000"),
                currency="EUR",
                transaction_type=TransactionType.income,
                classification=None,
            ),
            CurrentTransaction(
                transaction_id="transfer",
                account_id="account-1",
                timestamp=AT,
                amount=Decimal("-2.000000"),
                currency="USD",
                transaction_type=TransactionType.transfer,
                classification=TransactionClassification.internal_transfer,
            ),
        ),
    )

    assert result == (_amount("EUR", "15.000000"), _amount("USD", "-2.000000"))


def test_cash_delta_rejects_noncanonical_transfer() -> None:
    with pytest.raises(CurrentDeltaProjectionError):
        apply_cash_transactions(
            account_id="account-1",
            baseline=(),
            transactions=(
                CurrentTransaction(
                    transaction_id="bad",
                    account_id="account-1",
                    timestamp=AT,
                    amount=Decimal("1.000000"),
                    currency="EUR",
                    transaction_type=TransactionType.transfer,
                    classification=None,
                ),
            ),
        )


def test_investment_cash_transactions_change_cash_and_net_deposits_only() -> None:
    result = apply_investment_cash_transactions(
        account_id="account-1",
        baseline=(_amount("USD", "100.000000"),),
        transactions=(
            CurrentTransaction(
                transaction_id="card-debit",
                account_id="account-1",
                timestamp=AT,
                amount=Decimal("-12.000000"),
                currency="USD",
                transaction_type=TransactionType.expense,
                classification=TransactionClassification.real_expense,
            ),
            CurrentTransaction(
                transaction_id="cashback",
                account_id="account-1",
                timestamp=AT,
                amount=Decimal("4.000000"),
                currency="USD",
                transaction_type=TransactionType.income,
                classification=TransactionClassification.real_income,
            ),
            CurrentTransaction(
                transaction_id="investment-transfer",
                account_id="account-1",
                timestamp=AT,
                amount=Decimal("20.000000"),
                currency="USD",
                transaction_type=TransactionType.transfer,
                classification=TransactionClassification.investment_transfer,
            ),
        ),
    )

    assert result.cash_by_currency == (_amount("USD", "112.000000"),)
    assert [(item.kind.value, item.amount) for item in result.historical_metrics] == [
        ("net_deposit", Decimal("-12.000000")),
        ("net_deposit", Decimal("4.000000")),
        ("net_deposit", Decimal("20.000000")),
    ]


def test_investment_delta_advances_baseline_quantity_cost_and_cash() -> None:
    event = CurrentInvestmentEvent(
        event=HoldingPersistenceEvent(
            event_id="event-1",
            account_id="account-1",
            event_type=InvestmentEventType.trade,
            event_date=AT,
            external_id="external-1",
            movements=(
                _movement(
                    "asset",
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.incoming,
                    quantity="2.0000000000",
                ),
                _movement(
                    "cash",
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity="60.0000000000",
                ),
            ),
        ),
        realized_pnl=None,
        realized_pnl_currency=None,
    )

    result = apply_investment_events(
        account_id="account-1",
        baseline_positions=(_position(),),
        baseline_cash=(_amount("USD", "100.000000"),),
        events=(event,),
    )

    assert result.holdings.holdings[0].quantity == Decimal("4.0000000000")
    assert result.holdings.holdings[0].avg_buy_price == Decimal("25.0000000000")
    assert result.cash_by_currency == (_amount("USD", "40.000000"),)


def test_unknown_basis_baseline_remains_unknown_across_forward_transfer() -> None:
    baseline = replace(
        _position(),
        cost_basis=None,
        cost_currency=None,
        unrealized_pnl=None,
        native_cost_basis=None,
        native_cost_currency=None,
        native_cost_basis_by_currency=None,
        average_buy_price=None,
        average_buy_price_currency=None,
    )
    asset = replace(
        _movement(
            "asset",
            kind=InvestmentMovementKind.asset,
            direction=MovementDirection.incoming,
            quantity="1.0000000000",
        ),
        price_per_unit=None,
        value_amount=None,
        value_currency=None,
    )
    event = CurrentInvestmentEvent(
        event=HoldingPersistenceEvent(
            event_id="event-1",
            account_id="account-1",
            event_type=InvestmentEventType.asset_transfer,
            event_date=AT,
            external_id="external-1",
            movements=(asset,),
        ),
        realized_pnl=None,
        realized_pnl_currency=None,
    )

    result = apply_investment_events(
        account_id="account-1",
        baseline_positions=(baseline,),
        baseline_cash=(),
        events=(event,),
    )

    holding = result.holdings.holdings[0]
    assert holding.quantity == Decimal("3.0000000000")
    assert holding.avg_buy_price is None
    assert holding.cost_basis_by_currency is None
    assert result.has_asset_transfer is True


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        (MovementDirection.incoming, Decimal("30.000000")),
        (MovementDirection.outgoing, Decimal("-30.000000")),
    ],
)
def test_valued_asset_transfer_is_signed_external_cash_flow(
    direction: MovementDirection,
    expected: Decimal,
) -> None:
    asset = _movement(
        "asset",
        kind=InvestmentMovementKind.asset,
        direction=direction,
        quantity="1.0000000000",
    )
    event = CurrentInvestmentEvent(
        event=HoldingPersistenceEvent(
            event_id="event-1",
            account_id="account-1",
            event_type=InvestmentEventType.asset_transfer,
            event_date=AT,
            external_id="external-1",
            movements=(asset,),
        ),
        realized_pnl=None,
        realized_pnl_currency=None,
    )

    result = apply_investment_events(
        account_id="account-1",
        baseline_positions=(_position(),),
        baseline_cash=(),
        events=(event,),
    )

    assert result.has_asset_transfer is False
    assert len(result.historical_metrics) == 1
    metric = result.historical_metrics[0]
    assert metric.kind.value == "net_deposit"
    assert metric.currency == "USD"
    assert metric.amount == expected


def test_investment_delta_can_fully_close_a_baseline_position() -> None:
    event = CurrentInvestmentEvent(
        event=HoldingPersistenceEvent(
            event_id="event-1",
            account_id="account-1",
            event_type=InvestmentEventType.trade,
            event_date=AT,
            external_id="external-1",
            movements=(
                _movement(
                    "asset",
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.outgoing,
                    quantity="2.0000000000",
                ),
                _movement(
                    "cash",
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity="60.0000000000",
                ),
            ),
        ),
        realized_pnl=Decimal("20.000000"),
        realized_pnl_currency="USD",
    )

    result = apply_investment_events(
        account_id="account-1",
        baseline_positions=(_position(),),
        baseline_cash=(),
        events=(event,),
    )

    assert result.holdings.holdings == ()
    assert result.cash_by_currency == (_amount("USD", "60.000000"),)
    assert result.historical_metrics[0].amount == Decimal("20.000000")


def test_partial_sell_preserves_every_baseline_settlement_component() -> None:
    baseline = replace(
        _position(),
        cost_basis=Decimal("70.0000000000"),
        native_cost_basis=Decimal("70.0000000000"),
        native_cost_currency="CZK",
        native_cost_basis_by_currency=(
            _amount("EUR", "100.0000000000"),
            _amount("USD", "40.0000000000"),
        ),
    )
    event = CurrentInvestmentEvent(
        event=HoldingPersistenceEvent(
            event_id="event-1",
            account_id="account-1",
            event_type=InvestmentEventType.trade,
            event_date=AT,
            external_id="external-1",
            movements=(
                _movement(
                    "asset",
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.outgoing,
                    quantity="1.0000000000",
                ),
                _movement(
                    "cash",
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity="30.0000000000",
                ),
            ),
        ),
        realized_pnl=None,
        realized_pnl_currency=None,
    )

    result = apply_investment_events(
        account_id="account-1",
        baseline_positions=(baseline,),
        baseline_cash=(),
        events=(event,),
    )

    holding = result.holdings.holdings[0]
    assert holding.quantity == Decimal("1.0000000000")
    assert holding.avg_buy_price == Decimal("20.0000000000")
    assert holding.cost_basis_by_currency == (
        ("EUR", Decimal("50.0000000000")),
        ("USD", Decimal("20.0000000000")),
    )
