from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models.enums import CategoryType, TransactionType
from app.modules.categories.models import CategoryCreateRequest, CategoryUpdateRequest
from app.modules.transactions.models import TransactionCreateRequest, TransactionUpdateRequest


def test_transaction_models_preserve_exact_decimal_and_normalize_input() -> None:
    payload = TransactionCreateRequest.model_validate(
        {
            "date": "2026-08-09",
            "amount": "123456789.123456",
            "currency": " eur ",
            "type": "expense",
            "accountId": " account-1 ",
            "description": "  groceries  ",
            "idempotencyKey": " request-1 ",
        }
    )

    assert payload.date == datetime(2026, 8, 9)
    assert payload.amount == Decimal("123456789.123456")
    assert payload.currency == "EUR"
    assert payload.type is TransactionType.expense
    assert payload.account_id == "account-1"
    assert payload.description == "groceries"
    assert payload.idempotency_key == "request-1"


@pytest.mark.parametrize("amount", ["0", "-1", "1.0000001", "1000000000000.000000"])
def test_transaction_models_reject_out_of_contract_amounts(amount: str) -> None:
    with pytest.raises(ValidationError):
        TransactionCreateRequest.model_validate(
            {
                "date": "2026-08-09",
                "amount": amount,
                "currency": "CZK",
                "type": "income",
                "accountId": "account-1",
                "idempotencyKey": "request-1",
            }
        )


def test_transaction_update_requires_a_change_besides_idempotency() -> None:
    with pytest.raises(ValidationError):
        TransactionUpdateRequest.model_validate({"idempotencyKey": "request-1"})


def test_category_models_normalize_and_require_meaningful_updates() -> None:
    create = CategoryCreateRequest.model_validate(
        {
            "name": "  Food  ",
            "type": "expense",
            "parentId": "  parent-1  ",
            "idempotencyKey": " category-1 ",
        }
    )
    assert create.name == "Food"
    assert create.type is CategoryType.expense
    assert create.parent_id == "parent-1"
    assert create.idempotency_key == "category-1"

    with pytest.raises(ValidationError):
        CategoryUpdateRequest.model_validate({})
    with pytest.raises(ValidationError):
        CategoryUpdateRequest.model_validate({"name": "   "})
