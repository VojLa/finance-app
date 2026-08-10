"""R10-E2 public canonical numeric serialization acceptance."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic_core import PydanticSerializationError

from app.modules.current_value.api_models import CurrentDashboardAccountResponse
from app.modules.dashboard_snapshot.api_models import (
    DashboardAccountCardResponse,
    DashboardAssetTypeAllocationResponse,
    DashboardSnapshotSummaryResponse,
    DashboardTopPositionResponse,
)
from app.modules.portfolio_history.api_models import PortfolioHistoryPointResponse
from app.modules.portfolio_snapshot.api_models import (
    PortfolioCurrencyAmountResponse,
    PortfolioSnapshotPositionResponse,
    PortfolioSnapshotSummaryResponse,
)
from app.modules.portfolio_snapshot.models import AccountType, AssetType
from app.modules.portfolio_snapshot.multi_account_api_models import (
    MultiAccountPortfolioSummaryResponse,
)
from app.shared.numeric_serialization import (
    serialize_money,
    serialize_percentage,
    serialize_quantity,
    serialize_rate,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("0", "0.000000"),
        ("0.000000", "0.000000"),
        ("1", "1.000000"),
        ("1.2", "1.200000"),
        ("1.123456", "1.123456"),
        ("1.123456000000", "1.123456"),
        ("-1.123456000000", "-1.123456"),
        ("999999999999.999999", "999999999999.999999"),
        ("-0", "0.000000"),
        ("-0.000000", "0.000000"),
    ),
)
def test_money_serializer_emits_exact_canonical_scale(value: str, expected: str) -> None:
    assert serialize_money(Decimal(value)) == expected


@pytest.mark.parametrize(
    "value",
    (
        "1000000000000.000000",
        "-1000000000000.000000",
        "1.1234567",
        "NaN",
        "Infinity",
        "-Infinity",
        "1E+1000",
    ),
)
def test_money_serializer_rejects_nonrepresentable_values(value: str) -> None:
    with pytest.raises(ValueError, match=r"Canonical|representable"):
        serialize_money(Decimal(value))


def test_numeric_serializers_require_decimal_and_preserve_distinct_scales() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        serialize_money(1)  # type: ignore[arg-type]

    assert serialize_quantity(Decimal("2")) == "2.0000000000"
    assert serialize_rate(Decimal("24")) == "24.00000000"
    assert serialize_percentage(Decimal("12.5")) == "12.5000"
    with pytest.raises(ValueError, match="representable"):
        serialize_quantity(Decimal("1.00000000001"))
    with pytest.raises(ValueError, match="representable"):
        serialize_rate(Decimal("1.000000001"))
    with pytest.raises(ValueError, match="representable"):
        serialize_percentage(Decimal("1.00001"))


def _summary_values() -> dict[str, object]:
    return {
        "cash_value": Decimal("0E-14"),
        "cash_by_currency": (
            PortfolioCurrencyAmountResponse(
                currency="CZK",
                amount=Decimal("1800.00000000000000"),
            ),
        ),
        "investment_value": Decimal("1.20000000000000"),
        "investment_cost_basis": Decimal("1.00000000000000"),
        "liabilities_value": Decimal("1800.00000000000000"),
        "total_value": Decimal("-1798.80000000000000"),
        "net_deposits_value": Decimal("0E-14"),
        "net_deposits_by_currency": (),
        "realized_pnl_value": Decimal("0E-14"),
        "unrealized_pnl_value": Decimal("0.20000000000000"),
        "fees_value": Decimal("0E-14"),
        "taxes_value": Decimal("0E-14"),
    }


def test_portfolio_summary_and_breakdowns_serialize_all_money_canonically() -> None:
    account = PortfolioSnapshotSummaryResponse(**_summary_values(), position_count=1)
    aggregate = MultiAccountPortfolioSummaryResponse(
        **_summary_values(),
        account_count=1,
        position_count=1,
    )

    for payload in (
        account.model_dump(mode="json", by_alias=True),
        aggregate.model_dump(mode="json", by_alias=True),
    ):
        assert payload["cashValue"] == "0.000000"
        assert payload["cashByCurrency"] == [{"currency": "CZK", "amount": "1800.000000"}]
        assert payload["liabilitiesValue"] == "1800.000000"
        assert payload["totalValue"] == "-1798.800000"


def test_position_serialization_preserves_money_quantity_and_percentage_contracts() -> None:
    payload = PortfolioSnapshotPositionResponse(
        listing_id="listing-1",
        asset_id="asset-1",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        quantity=Decimal("2"),
        price_per_unit=Decimal("50"),
        price_currency="USD",
        price_timestamp="2032-08-01T12:30:00.123",
        value=Decimal("100.00000000000000"),
        value_currency="EUR",
        cost_basis=Decimal("80"),
        cost_currency="EUR",
        unrealized_pnl=Decimal("20"),
        allocation_pct=Decimal("100"),
        native_value=Decimal("100"),
        native_value_currency="USD",
        native_cost_basis=Decimal("80"),
        native_cost_currency="USD",
        native_cost_basis_by_currency=({"currency": "USD", "amount": Decimal("80")},),
    ).model_dump(mode="json", by_alias=True)

    assert payload["value"] == "100.000000"
    for field in (
        "quantity",
        "pricePerUnit",
        "costBasis",
        "unrealizedPnl",
        "nativeValue",
        "nativeCostBasis",
    ):
        assert payload[field].endswith(".0000000000")
    assert payload["allocationPct"] == "100.0000"


def _dashboard_summary() -> DashboardSnapshotSummaryResponse:
    return DashboardSnapshotSummaryResponse(
        total_value=Decimal("-1800.00000000000000"),
        assets_value=Decimal("0E-14"),
        liabilities_value=Decimal("1800.00000000000000"),
        cash_value=Decimal("0E-14"),
        investment_value=Decimal("0E-14"),
        investment_cost_basis=Decimal("0E-14"),
        unrealized_pnl_value=Decimal("0E-14"),
        realized_pnl_value=Decimal("0E-14"),
        net_deposits_value=Decimal("0E-14"),
        fees_value=Decimal("0E-14"),
        taxes_value=Decimal("0E-14"),
        account_count=1,
        investment_account_count=0,
        liability_account_count=1,
        position_count=0,
    )


def test_dashboard_account_models_serialize_money_canonically() -> None:
    values: dict[str, Any] = {
        "account_id": "account-1",
        "name": "Loan",
        "account_type": AccountType.loan,
        "account_currency": "EUR",
        "output_currency": "EUR",
        "total_value": Decimal("-75.000000000000"),
        "cash_value": Decimal("0E-12"),
        "investment_value": Decimal("0E-12"),
        "liabilities_value": Decimal("75.000000000000"),
        "net_deposits_value": Decimal("0E-12"),
        "unrealized_pnl_value": Decimal("0E-12"),
        "position_count": 0,
    }
    responses = (
        DashboardAccountCardResponse(
            snapshot_id="snapshot-1",
            primary_snapshot_id="primary-1",
            **values,
        ),
        CurrentDashboardAccountResponse(
            baseline_snapshot_id="snapshot-1",
            primary_baseline_snapshot_id="primary-1",
            **values,
        ),
    )
    for response in responses:
        payload = response.model_dump(mode="json", by_alias=True)
        assert payload["totalValue"] == "-75.000000"
        assert payload["liabilitiesValue"] == "75.000000"
        assert payload["netDepositsValue"] == "0.000000"


def test_dashboard_summary_allocations_and_positions_use_their_exact_contracts() -> None:
    summary = _dashboard_summary().model_dump(mode="json", by_alias=True)
    allocation = DashboardAssetTypeAllocationResponse(
        asset_type=AssetType.stock,
        value=Decimal("1800.00000000000000"),
        allocation_pct=Decimal("100.0000000000"),
        position_count=1,
        account_count=1,
    ).model_dump(mode="json", by_alias=True)
    position = DashboardTopPositionResponse(
        account_id="account-1",
        listing_id="listing-1",
        asset_id="asset-1",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        value=Decimal("1800.00000000000000"),
        value_currency="CZK",
        unrealized_pnl=Decimal("200.00000000000000"),
        allocation_pct=Decimal("100.0000000000"),
    ).model_dump(mode="json", by_alias=True)

    assert summary["liabilitiesValue"] == "1800.000000"
    assert summary["totalValue"] == "-1800.000000"
    assert allocation == {
        "assetType": "stock",
        "value": "1800.000000",
        "allocationPct": "100.0000",
        "positionCount": 1,
        "accountCount": 1,
    }
    assert position["value"] == "1800.000000"
    assert position["unrealizedPnl"] == "200.0000000000"
    assert position["allocationPct"] == "100.0000"


def test_history_money_uses_shared_fail_closed_serializer() -> None:
    payload = PortfolioHistoryPointResponse(
        timestamp="2032-08-01T00:00:00.000",
        cash_value=Decimal("125.000000000000"),
        investment_value=Decimal("75"),
        liabilities_value=Decimal("0E-12"),
        net_worth_value=Decimal("200.000000000000"),
    ).model_dump(mode="json", by_alias=True)
    assert payload["cashValue"] == "125.000000"
    assert payload["investmentValue"] == "75.000000"
    assert payload["liabilitiesValue"] == "0.000000"
    assert payload["netWorthValue"] == "200.000000"


def test_public_money_model_fails_closed_instead_of_rounding() -> None:
    model = PortfolioCurrencyAmountResponse(
        currency="EUR",
        amount=Decimal("1.1234567"),
    )
    with pytest.raises(PydanticSerializationError, match="representable"):
        model.model_dump(mode="json", by_alias=True)
