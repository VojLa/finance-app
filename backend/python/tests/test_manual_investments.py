from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models.enums import InvestmentEventType, InvestmentMovementKind, MovementDirection
from app.modules.investments.models import ManualInvestmentCreateRequest
from app.modules.investments.service import build_manual_event_plan


def _request(**values: object) -> ManualInvestmentCreateRequest:
    return ManualInvestmentCreateRequest.model_validate(
        {
            "accountId": "account-1",
            "idempotencyKey": "request-1",
            "date": "2026-08-10",
            **values,
        }
    )


def test_buy_plan_has_exact_asset_cash_and_fee_movements() -> None:
    plan = build_manual_event_plan(
        _request(
            type="buy",
            symbol="vwce",
            name="VWCE",
            assetType="etf",
            quantity="2.5000000000",
            pricePerUnit="100.0000000000",
            priceCurrency="EUR",
            totalAmount="250.0000000000",
            totalCurrency="EUR",
            fee="1.0000000000",
            feeCurrency="EUR",
        )
    )

    assert plan.event_type is InvestmentEventType.trade
    assert plan.asset is not None
    assert plan.asset.symbol == "VWCE"
    assert plan.asset.provider.value == "manual"
    assert tuple((item.kind, item.direction) for item in plan.movements) == (
        (InvestmentMovementKind.asset, MovementDirection.incoming),
        (InvestmentMovementKind.cash, MovementDirection.outgoing),
        (InvestmentMovementKind.fee, MovementDirection.outgoing),
    )
    assert plan.movements[0].quantity == Decimal("2.5000000000")
    assert plan.movements[1].quantity == Decimal("250.0000000000")


def test_conversion_requires_two_exact_cash_legs() -> None:
    plan = build_manual_event_plan(
        _request(
            type="currency_conversion",
            conversionFromAmount="100.0000000000",
            conversionFromCurrency="EUR",
            conversionToAmount="110.0000000000",
            conversionToCurrency="USD",
        )
    )

    assert plan.event_type is InvestmentEventType.currency_conversion
    assert tuple((item.direction, item.currency) for item in plan.movements) == (
        (MovementDirection.outgoing, "EUR"),
        (MovementDirection.incoming, "USD"),
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"type": "buy", "symbol": "VWCE", "assetType": "etf"},
        {"type": "currency_conversion", "totalAmount": "1", "totalCurrency": "EUR"},
        {
            "type": "interest",
            "symbol": "VWCE",
            "assetType": "etf",
            "totalAmount": "1",
            "totalCurrency": "EUR",
        },
        {
            "type": "deposit",
            "symbol": "VWCE",
            "assetType": "etf",
            "quantity": "1",
            "totalAmount": "1",
            "totalCurrency": "EUR",
        },
    ),
)
def test_invalid_or_ambiguous_actions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _request(**payload)
