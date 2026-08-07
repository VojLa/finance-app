from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from decimal import Decimal

import pytest

from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.models import PortfolioSnapshotSource
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CashBalanceEvidence,
    CurrencyAmount,
    LiabilityBalanceEvidence,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceMetadata,
    ExpectedAccountSnapshotRow,
    build_account_snapshot_persistence_projection,
)

SNAPSHOT_AT = datetime(2036, 1, 10, 12, 0)
CREATED_AT = datetime(2036, 1, 10, 12, 0, 0, 123000)


def _rate(
    base: str,
    quote: str,
    value: str,
    *,
    rate_id: str,
) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=rate_id,
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(value),
        source=ExchangeRateSource.cnb,
        timestamp=SNAPSHOT_AT,
    )


def _holding(
    account_id: str,
    *,
    cost_currency: str,
) -> SnapshotHoldingEvidence:
    return SnapshotHoldingEvidence(
        holding_id=f"{account_id}-holding",
        account_id=account_id,
        asset_id=f"{account_id}-asset",
        listing_id=f"{account_id}-listing",
        listing_asset_id=f"{account_id}-asset",
        symbol="ASSET",
        asset_type=AssetType.stock,
        quantity=Decimal("2"),
        average_buy_price=Decimal("80"),
        cost_currency=cost_currency,
    )


def _price(
    account_id: str,
    *,
    currency: str,
) -> SelectedPriceEvidence:
    return SelectedPriceEvidence(
        price_id=f"{account_id}-price",
        asset_id=f"{account_id}-asset",
        listing_id=f"{account_id}-listing",
        symbol="ASSET",
        price=Decimal("100"),
        currency=currency,
        source=PriceSource.twelve_data,
        timestamp=SNAPSHOT_AT,
    )


def _investment_input(
    account_id: str,
    *,
    price_currency: str,
    cost_currency: str,
    rates: tuple[SelectedExchangeRateEvidence, ...],
    output_currency: str = "CZK",
) -> AccountSnapshotProjectionInput:
    return AccountSnapshotProjectionInput(
        account_id=account_id,
        account_type=AccountType.broker,
        account_currency="EUR",
        output_currency=output_currency,
        snapshot_timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.minute,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        holdings=(_holding(account_id, cost_currency=cost_currency),),
        prices=(_price(account_id, currency=price_currency),),
        exchange_rates=rates,
        cash_balances=(),
        liabilities=(),
    )


def _persist(
    valuation,
    *,
    selected_price_ids: tuple[str, ...],
    selected_rate_ids: tuple[str, ...],
    liability_id: str | None = None,
) -> ExpectedAccountSnapshotRow:
    zero = ExactSnapshotMetric(Decimal(0), ())
    unrealized = ExactSnapshotMetric(
        valuation.investment_value - valuation.investment_cost_basis,
        None if valuation.items else (),
    )
    evidence = CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=unrealized,
        fees=zero,
        taxes=zero,
        selected_price_ids=selected_price_ids,
        selected_snapshot_exchange_rate_ids=selected_rate_ids,
        selected_historical_exchange_rate_ids=(),
        selected_liability_balance_id=liability_id,
        selected_liability_effective_at=SNAPSHOT_AT if liability_id else None,
        selected_liability_source=LiabilityBalanceSource.statement if liability_id else None,
    )
    return build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=CREATED_AT,
            created_at=CREATED_AT,
            is_recalculated=True,
        ),
    ).snapshot


def test_same_currency_cash_account_is_exactly_representable() -> None:
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-a",
            account_type=AccountType.bank,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(),
            cash_balances=(
                CashBalanceEvidence(
                    balance_id="account-a-cash",
                    account_id="account-a",
                    currency="CZK",
                    amount=Decimal("1000.000000"),
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            liabilities=(),
        )
    )

    assert valuation.currency == "CZK"
    assert valuation.cash_value == Decimal("1000.000000")
    assert valuation.cash_value_by_currency == (
        CurrencyAmount(currency="CZK", amount=Decimal("1000.000000")),
    )
    assert valuation.exchange_rates == ()


def test_eur_native_investment_account_still_persists_user_output_scalars() -> None:
    account_id = "account-b"
    rate = _rate("EUR", "CZK", "25.00000000", rate_id="account-b-eur-czk")
    valuation = build_account_snapshot_projection(
        _investment_input(
            account_id,
            price_currency="EUR",
            cost_currency="EUR",
            rates=(rate,),
        )
    )
    persisted = _persist(
        valuation,
        selected_price_ids=(f"{account_id}-price",),
        selected_rate_ids=(rate.rate_id,),
    )

    assert valuation.currency == "CZK"
    assert valuation.investment_value == Decimal("5000.000000")
    assert valuation.investment_value_by_currency == (
        CurrencyAmount(currency="EUR", amount=Decimal("200.0000000000")),
    )
    assert persisted.currency == "CZK"
    assert persisted.investment_value == Decimal("5000.000000")
    assert "account_currency_summary" not in persisted.model_values()


def test_mixed_native_eur_account_requires_missing_direct_usd_eur_rate() -> None:
    account_id = "account-c"
    usd_czk = _rate("USD", "CZK", "23.00000000", rate_id="account-c-usd-czk")
    eur_czk = _rate("EUR", "CZK", "25.00000000", rate_id="account-c-eur-czk")
    output_valuation = build_account_snapshot_projection(
        _investment_input(
            account_id,
            price_currency="USD",
            cost_currency="EUR",
            rates=(usd_czk, eur_czk),
        )
    )

    assert output_valuation.currency == "CZK"
    assert {
        (rate.base_currency, rate.quote_currency) for rate in output_valuation.exchange_rates
    } == {("EUR", "CZK"), ("USD", "CZK")}
    assert output_valuation.investment_value_by_currency == (
        CurrencyAmount(currency="USD", amount=Decimal("200.0000000000")),
    )

    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _investment_input(
                account_id,
                price_currency="USD",
                cost_currency="EUR",
                rates=(usd_czk, eur_czk),
                output_currency="EUR",
            )
        )


def test_liability_native_breakdown_is_validated_but_not_persisted() -> None:
    account_id = "account-d"
    eur_czk = _rate("EUR", "CZK", "25.00000000", rate_id="account-d-eur-czk")
    liability_id = "account-d-liability"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.loan,
            account_currency="EUR",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(eur_czk,),
            cash_balances=(),
            liabilities=(
                LiabilityBalanceEvidence(
                    liability_id=liability_id,
                    account_id=account_id,
                    currency="EUR",
                    amount=Decimal("100.000000"),
                    timestamp=SNAPSHOT_AT,
                ),
            ),
        )
    )
    persisted = _persist(
        valuation,
        selected_price_ids=(),
        selected_rate_ids=(eur_czk.rate_id,),
        liability_id=liability_id,
    )

    assert valuation.liabilities_value == Decimal("2500.000000")
    assert valuation.liabilities_value_by_currency == (
        CurrencyAmount(currency="EUR", amount=Decimal("100.000000")),
    )
    assert persisted.currency == "CZK"
    assert persisted.liabilities_value == Decimal("2500.000000")
    assert "liabilities_value_by_currency" not in {
        field.name for field in fields(ExpectedAccountSnapshotRow)
    }
    assert "liabilities_value_by_currency" not in persisted.model_values()


def test_portfolio_read_contract_lacks_complete_account_currency_evidence() -> None:
    source_fields = {field.name for field in fields(PortfolioSnapshotSource)}

    assert "investment_value_by_currency" not in source_fields
    assert "investment_cost_basis_by_currency" not in source_fields
    assert "liabilities_value_by_currency" not in source_fields
    assert "realized_pnl_by_currency" not in source_fields
    assert "unrealized_pnl_by_currency" not in source_fields
    assert "fees_by_currency" not in source_fields
    assert "taxes_by_currency" not in source_fields
    assert "exchange_rates" not in source_fields
