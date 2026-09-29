"""Small deterministic Raiffeisenbank exports for parser and reconciliation tests.

The generated statements contain synthetic names, account identifiers, and values.
They preserve the evidence relationships and aggregate counts used by the tests
without depending on local or private statement exports.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from datetime import date, timedelta
from functools import lru_cache
from io import StringIO

_CARD_FIELDS = (
    "Datum transakce",
    "Zaúčtovaná částka",
    "Měna zaúčtování",
    "Typ transakce",
    "Číslo kreditní karty",
    "Název Obchodníka",
    "Popis/Místo transakce",
    "Město",
    "Vlastní poznámka",
    "Datum zúčtování",
)
_ACCOUNT_FIELDS = (
    "Datum provedení",
    "Zaúčtovaná částka",
    "Měna účtu",
    "Typ transakce",
    "Název protiúčtu",
    "Id transakce",
    "Číslo účtu",
    "Číslo protiúčtu",
    "Datum zaúčtování",
    "VS",
    "Původní částka",
    "Původní měna",
)

type _Row = dict[str, str]


def _csv_bytes(fields: tuple[str, ...], rows: list[_Row]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _card_row(
    *,
    transaction_date: str,
    amount: int,
    transaction_type: str,
    card_number: str,
    merchant: str,
    description: str,
    booking_date: str = "01.01.2024 18:00:00",
) -> _Row:
    return {
        "Datum transakce": transaction_date,
        "Zaúčtovaná částka": str(amount),
        "Měna zaúčtování": "CZK",
        "Typ transakce": transaction_type,
        "Číslo kreditní karty": card_number,
        "Název Obchodníka": merchant,
        "Popis/Místo transakce": description,
        "Město": "Synthetic City",
        "Vlastní poznámka": "",
        "Datum zúčtování": booking_date,
    }


def _card_exports() -> tuple[list[_Row], list[_Row]]:
    current: list[_Row] = []
    history: list[_Row] = []

    for index in range(35):
        transaction_date = date(2024, 5, 2) + timedelta(days=index)
        current.append(
            _card_row(
                transaction_date=transaction_date.strftime("%d.%m.%Y"),
                amount=2000 if index == 0 else 200 + index,
                transaction_type="Splátka klienta",
                card_number="999999XXXXXX2067",
                merchant=f"Synthetic card repayment {index:02d}",
                description="Synthetic credit card repayment",
                booking_date=transaction_date.strftime("%d.%m.%Y 12:00:00"),
            )
        )

    for index in range(36):
        amount = 71 if index == 35 else 48
        row = _card_row(
            transaction_date="01.01.2024",
            amount=-amount,
            transaction_type="Synthetic purchase",
            card_number="999999XXXXXX2067",
            merchant=f"Synthetic repeated purchase {index:02d}",
            description="Synthetic repeated card purchase",
        )
        current.extend((row, row.copy()))

    current_singles: list[_Row] = []
    for index in range(893):
        is_income = index < 300
        current_singles.append(
            _card_row(
                transaction_date="01.01.2024",
                amount=index + 1 if is_income else -(index + 1),
                transaction_type="Synthetic card activity",
                card_number="999999XXXXXX2067",
                merchant=f"Synthetic current activity {index:04d}",
                description="Synthetic card activity",
            )
        )
    current.extend(current_singles)

    history.extend(row.copy() for row in current_singles[300:316])
    for index in range(984):
        history.append(
            _card_row(
                transaction_date="02.01.2024",
                amount=-(index + 1),
                transaction_type="Synthetic card activity",
                card_number="999999XXXXXX2067",
                merchant=f"Synthetic history activity {index:04d}",
                description="Synthetic card activity",
            )
        )
    assert len(current) == len(history) == 1000
    return current, history


def _account_row(
    *,
    transaction_date: str,
    amount: int,
    currency: str,
    transaction_type: str,
    account_number: str,
    counterparty_account: str,
    transaction_id: str,
    booking_date: str,
    variable_symbol: str = "",
    original_amount: str = "",
    original_currency: str = "",
) -> _Row:
    return {
        "Datum provedení": transaction_date,
        "Zaúčtovaná částka": str(amount),
        "Měna účtu": currency,
        "Typ transakce": transaction_type,
        "Název protiúčtu": "Synthetic counterparty",
        "Id transakce": transaction_id,
        "Číslo účtu": account_number,
        "Číslo protiúčtu": counterparty_account,
        "Datum zaúčtování": booking_date,
        "VS": variable_symbol,
        "Původní částka": original_amount,
        "Původní měna": original_currency,
    }


def _account_exports() -> dict[str, bytes]:
    basic: list[_Row] = []
    savings: list[_Row] = []
    euro: list[_Row] = []
    basic_number = "TEST-BASIC-CZK"
    savings_number = "TEST-SAVINGS-CZK"

    for index in range(269):
        transaction_date = date(2024, 5, 2) + timedelta(days=index)
        date_text = transaction_date.strftime("%d.%m.%Y")
        booking_text = transaction_date.strftime("%d.%m.%Y 09:00:00")
        amount = 2000 if index == 0 else 100 + index
        bank_amount = -amount if index % 2 == 0 else amount
        savings_amount = -bank_amount
        basic.append(
            _account_row(
                transaction_date=date_text,
                amount=bank_amount,
                currency="CZK",
                transaction_type="Synthetic transfer",
                account_number=basic_number,
                counterparty_account=savings_number,
                transaction_id=f"synthetic-internal-{index:03d}",
                booking_date=booking_text,
            )
        )
        savings.append(
            _account_row(
                transaction_date=date_text,
                amount=savings_amount,
                currency="CZK",
                transaction_type="Synthetic transfer",
                account_number=savings_number,
                counterparty_account=basic_number,
                transaction_id=f"synthetic-internal-{index:03d}",
                booking_date=booking_text,
            )
        )

    for index in range(35):
        transaction_date = date(2024, 5, 2) + timedelta(days=index)
        basic.append(
            _account_row(
                transaction_date=transaction_date.strftime("%d.%m.%Y"),
                amount=-(2000 if index == 0 else 200 + index),
                currency="CZK",
                transaction_type="Jednorázová úhrada",
                account_number=basic_number,
                counterparty_account="TEST-CARD-ACCOUNT",
                transaction_id=f"synthetic-card-payment-{index:02d}",
                booking_date=transaction_date.strftime("%d.%m.%Y 12:00:00"),
                variable_symbol="9999992067",
            )
        )

    for index in range(9):
        transaction_date = date(2025, 6, 1) + timedelta(days=index)
        date_text = transaction_date.strftime("%d.%m.%Y")
        booking_text = transaction_date.strftime("%d.%m.%Y 14:00:00")
        czk_amount = 2500 + index
        euro_amount = 100 + index
        common = {
            "transaction_date": date_text,
            "transaction_type": "Konverze",
            "transaction_id": f"synthetic-exchange-czk-{index:02d}",
            "booking_date": booking_text,
        }
        basic.append(
            _account_row(
                **common,
                amount=-czk_amount,
                currency="CZK",
                account_number=basic_number,
                counterparty_account="",
                original_amount=str(euro_amount),
                original_currency="EUR",
            )
        )
        euro.append(
            _account_row(
                **{
                    **common,
                    "transaction_id": f"synthetic-exchange-eur-{index:02d}",
                },
                amount=euro_amount,
                currency="EUR",
                account_number=basic_number,
                counterparty_account="",
                original_amount=str(czk_amount),
                original_currency="CZK",
            )
        )

    for index in range(2990):
        is_income = index < 362
        basic.append(
            _account_row(
                transaction_date=(date(2025, 1, 1) + timedelta(days=index)).strftime("%d.%m.%Y"),
                amount=index + 1 if is_income else -(index + 1),
                currency="CZK",
                transaction_type="Synthetic income" if is_income else "Synthetic expense",
                account_number=basic_number,
                counterparty_account="",
                transaction_id=f"synthetic-unpaired-{index:04d}",
                booking_date=(date(2025, 1, 1) + timedelta(days=index)).strftime(
                    "%d.%m.%Y 16:00:00"
                ),
            )
        )

    # The assertions exercise a specific reciprocal Basic/Savings pair whose
    # source-account identifiers are clearly synthetic.
    assert basic[0]["Číslo protiúčtu"] == savings_number
    return {
        "Basic CZK.csv": _csv_bytes(_ACCOUNT_FIELDS, basic),
        "Savings.csv": _csv_bytes(_ACCOUNT_FIELDS, savings),
        "EUR.csv": _csv_bytes(_ACCOUNT_FIELDS, euro),
    }


@lru_cache(maxsize=1)
def card_multiset_exports() -> Mapping[str, bytes]:
    """Return two parser-valid synthetic exports with the multiset test profile."""
    current, history = _card_exports()
    return {
        "Credit.csv": _csv_bytes(_CARD_FIELDS, current),
        "Credit 2.csv": _csv_bytes(_CARD_FIELDS, history),
    }


@lru_cache(maxsize=1)
def reconciliation_exports() -> Mapping[str, bytes]:
    """Return parser-valid synthetic exports with exact reconciliation totals."""
    return {
        **_account_exports(),
        **card_multiset_exports(),
    }
