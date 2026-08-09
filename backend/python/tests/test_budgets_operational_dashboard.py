from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models.enums import TransactionClassification, TransactionType
from app.db.models.transactions import TransactionModel
from app.modules.budgets.models import BudgetSaveRequest
from app.modules.budgets.service import (
    BudgetUnavailableError,
    _percentage,
    month_range,
    previous_month,
    transaction_czk,
)


def _transaction(**overrides: object) -> TransactionModel:
    values: dict[str, object] = {
        "id": "transaction-1",
        "date": datetime(2026, 8, 1),
        "booking_date": None,
        "amount": Decimal("-10.000000"),
        "currency": "CZK",
        "reporting_amount": None,
        "reporting_currency": None,
        "type": TransactionType.expense,
        "classification": TransactionClassification.real_expense,
        "description": None,
        "note": None,
        "counterparty": None,
        "external_id": None,
        "is_reviewed": True,
        "archived_at": None,
        "deleted_at": None,
        "category_id": None,
        "account_id": "account-1",
        "import_batch_id": None,
        "created_at": datetime(2026, 8, 1),
        "updated_at": datetime(2026, 8, 1),
    }
    values.update(overrides)
    return TransactionModel(**values)  # type: ignore[arg-type]


def test_budget_request_preserves_exact_money_and_rejects_duplicates() -> None:
    payload = BudgetSaveRequest.model_validate(
        {
            "month": 8,
            "year": 2026,
            "rollover": True,
            "items": [{"categoryId": "food", "amount": "123.456789", "currency": "czk"}],
        }
    )
    assert payload.items[0].amount == Decimal("123.456789")
    assert payload.items[0].currency == "CZK"

    with pytest.raises(ValidationError):
        BudgetSaveRequest.model_validate(
            {
                "month": 8,
                "year": 2026,
                "items": [
                    {"categoryId": "food", "amount": "1", "currency": "CZK"},
                    {"categoryId": "food", "amount": "2", "currency": "CZK"},
                ],
            }
        )


def test_month_boundaries_and_percentage_are_deterministic() -> None:
    assert month_range(12, 2026) == (datetime(2026, 12, 1), datetime(2027, 1, 1))
    assert previous_month(1, 2026) == (12, 2025)
    assert _percentage(Decimal("1"), Decimal("3")) == Decimal("33.3333")
    assert _percentage(Decimal("2"), Decimal("1")) == Decimal("100.0000")


def test_operational_conversion_uses_only_persisted_czk_evidence() -> None:
    assert transaction_czk(_transaction()) == Decimal("-10.000000")
    assert transaction_czk(
        _transaction(
            amount=Decimal("-1.000000"),
            currency="EUR",
            reporting_amount=Decimal("-25.000000"),
            reporting_currency="CZK",
        )
    ) == Decimal("-25.000000")

    with pytest.raises(BudgetUnavailableError):
        transaction_czk(_transaction(currency="EUR"))
    with pytest.raises(BudgetUnavailableError):
        transaction_czk(_transaction(amount=Decimal("10.000000")))
