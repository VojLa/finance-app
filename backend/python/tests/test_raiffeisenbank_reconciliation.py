from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.db.models.enums import (
    AccountType,
    ImportSource,
    TransactionClassification,
)
from app.modules.imports.classification import TransactionPostingIntent, classify_import_row
from app.modules.imports.parsers import parse_import_file
from app.modules.imports.raiffeisenbank import normalize_raiffeisenbank_import_row
from app.modules.imports.raiffeisenbank_card_multiset import (
    RaiffeisenbankCardCandidate,
    plan_raiffeisenbank_card_multiset,
)
from app.modules.imports.raiffeisenbank_reconciliation import (
    RaiffeisenbankPostedTransactionIdentity,
    RaiffeisenbankReconciliationAccount,
    RaiffeisenbankReconciliationCandidate,
    RaiffeisenbankReconciliationEvidenceError,
    plan_raiffeisenbank_reconciliation,
)

RB_FIXTURES = Path(__file__).parents[3] / "test_imports" / "RB"


def _accounts() -> tuple[RaiffeisenbankReconciliationAccount, ...]:
    return (
        RaiffeisenbankReconciliationAccount(
            account_id="basic-czk",
            owner_id="owner",
            account_type=AccountType.bank,
            currency="CZK",
        ),
        RaiffeisenbankReconciliationAccount(
            account_id="savings-czk",
            owner_id="owner",
            account_type=AccountType.savings,
            currency="CZK",
        ),
        RaiffeisenbankReconciliationAccount(
            account_id="basic-eur",
            owner_id="owner",
            account_type=AccountType.bank,
            currency="EUR",
        ),
        RaiffeisenbankReconciliationAccount(
            account_id="credit-czk",
            owner_id="owner",
            account_type=AccountType.credit_card,
            currency="CZK",
        ),
    )


def _rows(filename: str):
    return parse_import_file(
        ImportSource.raiffeisenbank,
        (RB_FIXTURES / filename).read_bytes(),
        encoding=None,
    )


def _candidate(
    *,
    account_id: str,
    transaction_id: str,
    raw_data: dict[str, str | None],
) -> RaiffeisenbankReconciliationCandidate:
    normalized = normalize_raiffeisenbank_import_row(account_id=account_id, raw_data=raw_data)
    assert normalized.data is not None
    intent = classify_import_row(
        source=ImportSource.raiffeisenbank,
        normalized_data=normalized.data,
    )
    assert isinstance(intent, TransactionPostingIntent)
    return RaiffeisenbankReconciliationCandidate(
        posted=RaiffeisenbankPostedTransactionIdentity(
            transaction_id=transaction_id,
            account_id=account_id,
            date=datetime.fromisoformat(intent.date),
            amount=intent.amount,
            currency=intent.currency,
            transaction_type=intent.transaction_type,
            classification=intent.transaction_classification,
            external_id=normalized.data["external_id"],
        ),
        raw_data=raw_data,
    )


@pytest.fixture(scope="module")
def fixture_input() -> tuple[
    tuple[RaiffeisenbankReconciliationAccount, ...],
    tuple[RaiffeisenbankReconciliationCandidate, ...],
]:
    candidates: list[RaiffeisenbankReconciliationCandidate] = []
    for filename, account_id in (
        ("Basic CZK.csv", "basic-czk"),
        ("Savings.csv", "savings-czk"),
        ("EUR.csv", "basic-eur"),
    ):
        candidates.extend(
            _candidate(
                account_id=account_id,
                transaction_id=f"{filename}:{row.row_number}",
                raw_data=row.raw_data,
            )
            for row in _rows(filename)
        )

    card_rows: list[tuple[str, str, int, dict[str, str | None], dict[str, object]]] = []
    for filename, batch_id in (
        ("Credit.csv", "credit-current"),
        ("Credit 2.csv", "credit-history"),
    ):
        for row in _rows(filename):
            normalized = normalize_raiffeisenbank_import_row(
                account_id="credit-czk",
                raw_data=row.raw_data,
            )
            assert normalized.data is not None
            card_rows.append((filename, batch_id, row.row_number, row.raw_data, normalized.data))
    card_plan = plan_raiffeisenbank_card_multiset(
        account_id="credit-czk",
        candidates=[
            RaiffeisenbankCardCandidate(
                batch_id=batch_id,
                row_id=f"{filename}:{row_number}",
                row_number=row_number,
                raw_data=raw_data,
                normalized_data=normalized_data,
            )
            for filename, batch_id, row_number, raw_data, normalized_data in card_rows
        ],
    )
    canonical_card_rows = set(card_plan.canonical_row_ids)
    assert card_plan.physical_row_count == 2_000
    assert card_plan.canonical_row_count == 1_984
    candidates.extend(
        _candidate(
            account_id="credit-czk",
            transaction_id=f"{filename}:{row_number}",
            raw_data=raw_data,
        )
        for filename, _, row_number, raw_data, _ in card_rows
        if f"{filename}:{row_number}" in canonical_card_rows
    )
    assert len(candidates) == 5_565
    return _accounts(), tuple(candidates)


def test_real_rb_fixtures_plan_all_and_only_supported_pairs(
    fixture_input: tuple[
        tuple[RaiffeisenbankReconciliationAccount, ...],
        tuple[RaiffeisenbankReconciliationCandidate, ...],
    ],
) -> None:
    accounts, candidates = fixture_input
    plan = plan_raiffeisenbank_reconciliation(accounts=accounts, candidates=candidates)

    assert len(plan.pairs) == 313
    assert len(plan.paired_transaction_ids) == 626
    assert {
        classification: sum(pair.classification is classification for pair in plan.pairs)
        for classification in (
            TransactionClassification.internal_transfer,
            TransactionClassification.credit_card_payment,
            TransactionClassification.cash_exchange,
        )
    } == {
        TransactionClassification.internal_transfer: 269,
        TransactionClassification.credit_card_payment: 35,
        TransactionClassification.cash_exchange: 9,
    }
    assert len(plan.unpaired_transaction_ids) == 4_939
    assert len(plan.remaining_real_income_transaction_ids) == 662
    assert len(plan.remaining_real_expense_transaction_ids) == 4_277

    by_id = {candidate.posted.transaction_id: candidate for candidate in candidates}
    repayment = next(
        candidate
        for candidate in candidates
        if candidate.posted.account_id == "credit-czk"
        and candidate.posted.date.date().isoformat() == "2024-05-02"
        and candidate.posted.amount == Decimal("2000")
    )
    repayment_pair = next(
        pair
        for pair in plan.pairs
        if repayment.posted.transaction_id in {pair.from_transaction_id, pair.to_transaction_id}
    )
    assert repayment_pair.classification is TransactionClassification.credit_card_payment
    assert by_id[repayment_pair.from_transaction_id].posted.account_id == "basic-czk"
    assert repayment.raw_data["Číslo kreditní karty"] == "520655XXXXXX2067"
    assert by_id[repayment_pair.from_transaction_id].raw_data["VS"] == "4668142067"
    assert (
        by_id[repayment_pair.from_transaction_id].raw_data["Číslo protiúčtu"] == "1101083110/5500"
    )
    same_day_savings_transfer = next(
        candidate
        for candidate in candidates
        if candidate.posted.account_id == "basic-czk"
        and candidate.posted.date.date().isoformat() == "2024-05-02"
        and candidate.posted.amount == Decimal("-2000")
        and candidate.raw_data["Číslo protiúčtu"] == "1530315311/5500"
    )
    savings_transfer_pair = next(
        pair
        for pair in plan.pairs
        if same_day_savings_transfer.posted.transaction_id
        in {pair.from_transaction_id, pair.to_transaction_id}
    )
    assert savings_transfer_pair.classification is TransactionClassification.internal_transfer
    assert savings_transfer_pair.pair_id != repayment_pair.pair_id


def test_real_fixture_plan_is_reorder_stable_and_late_arrival_converges(
    fixture_input: tuple[
        tuple[RaiffeisenbankReconciliationAccount, ...],
        tuple[RaiffeisenbankReconciliationCandidate, ...],
    ],
) -> None:
    accounts, candidates = fixture_input
    ordered = plan_raiffeisenbank_reconciliation(accounts=accounts, candidates=candidates)
    reordered = plan_raiffeisenbank_reconciliation(
        accounts=reversed(accounts),
        candidates=reversed(candidates),
    )
    assert reordered == ordered

    delayed_pair = ordered.pairs[0]
    delayed_id = delayed_pair.to_transaction_id
    before_arrival = plan_raiffeisenbank_reconciliation(
        accounts=accounts,
        candidates=[
            candidate for candidate in candidates if candidate.posted.transaction_id != delayed_id
        ],
    )
    after_arrival = plan_raiffeisenbank_reconciliation(
        accounts=accounts,
        candidates=[
            *(
                candidate
                for candidate in candidates
                if candidate.posted.transaction_id != delayed_id
            ),
            next(
                candidate
                for candidate in candidates
                if candidate.posted.transaction_id == delayed_id
            ),
        ],
    )
    assert delayed_pair.pair_id not in {pair.pair_id for pair in before_arrival.pairs}
    assert after_arrival == ordered


def test_ambiguous_strong_counterpart_fails_closed(
    fixture_input: tuple[
        tuple[RaiffeisenbankReconciliationAccount, ...],
        tuple[RaiffeisenbankReconciliationCandidate, ...],
    ],
) -> None:
    accounts, candidates = fixture_input
    plan = plan_raiffeisenbank_reconciliation(accounts=accounts, candidates=candidates)
    card_pair = next(
        pair
        for pair in plan.pairs
        if pair.classification is TransactionClassification.credit_card_payment
    )
    duplicate_bank = replace(
        next(
            candidate
            for candidate in candidates
            if candidate.posted.transaction_id == card_pair.from_transaction_id
        ),
        posted=replace(
            next(
                candidate
                for candidate in candidates
                if candidate.posted.transaction_id == card_pair.from_transaction_id
            ).posted,
            transaction_id="ambiguous-strong-bank-counterpart",
        ),
    )

    with pytest.raises(RaiffeisenbankReconciliationEvidenceError):
        plan_raiffeisenbank_reconciliation(
            accounts=accounts, candidates=[*candidates, duplicate_bank]
        )


def test_foreign_owner_and_missing_credit_source_corroboration_remain_unpaired(
    fixture_input: tuple[
        tuple[RaiffeisenbankReconciliationAccount, ...],
        tuple[RaiffeisenbankReconciliationCandidate, ...],
    ],
) -> None:
    accounts, candidates = fixture_input
    full = plan_raiffeisenbank_reconciliation(accounts=accounts, candidates=candidates)
    internal = next(
        pair
        for pair in full.pairs
        if pair.classification is TransactionClassification.internal_transfer
    )
    internal_candidates = [
        candidate
        for candidate in candidates
        if candidate.posted.transaction_id
        in {internal.from_transaction_id, internal.to_transaction_id}
    ]
    foreign_accounts = tuple(
        replace(account, owner_id="foreign-owner")
        if account.account_id == "savings-czk"
        else account
        for account in accounts
    )
    foreign = plan_raiffeisenbank_reconciliation(
        accounts=foreign_accounts,
        candidates=internal_candidates,
    )
    assert not foreign.pairs
    assert foreign.unpaired_transaction_ids == tuple(
        sorted(candidate.posted.transaction_id for candidate in internal_candidates)
    )

    credit_pair = next(
        pair
        for pair in full.pairs
        if pair.classification is TransactionClassification.credit_card_payment
    )
    credit_candidates = [
        candidate
        for candidate in candidates
        if candidate.posted.transaction_id
        in {credit_pair.from_transaction_id, credit_pair.to_transaction_id}
    ]
    bank = next(candidate for candidate in credit_candidates if candidate.posted.amount < 0)
    without_variable_symbol = replace(
        bank,
        raw_data={**bank.raw_data, "VS": ""},
    )
    uncorroborated = plan_raiffeisenbank_reconciliation(
        accounts=accounts,
        candidates=[
            candidate
            if candidate.posted.transaction_id != bank.posted.transaction_id
            else without_variable_symbol
            for candidate in credit_candidates
        ],
    )
    assert not uncorroborated.pairs


@pytest.mark.parametrize("case", ["wrong-account", "corrupt-amount"])
def test_wrong_account_or_corrupt_posted_evidence_fails_closed(
    fixture_input: tuple[
        tuple[RaiffeisenbankReconciliationAccount, ...],
        tuple[RaiffeisenbankReconciliationCandidate, ...],
    ],
    case: str,
) -> None:
    accounts, candidates = fixture_input
    original = next(
        candidate for candidate in candidates if candidate.posted.account_id == "basic-czk"
    )
    malformed = (
        replace(original, posted=replace(original.posted, account_id="credit-czk"))
        if case == "wrong-account"
        else replace(original, raw_data={**original.raw_data, "Zaúčtovaná částka": "999"})
    )

    with pytest.raises(RaiffeisenbankReconciliationEvidenceError):
        plan_raiffeisenbank_reconciliation(
            accounts=accounts,
            candidates=[
                malformed
                if candidate.posted.transaction_id == original.posted.transaction_id
                else candidate
                for candidate in candidates
            ],
        )
