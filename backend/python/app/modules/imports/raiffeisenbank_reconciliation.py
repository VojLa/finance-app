"""Pure reconciliation planning for supported Raiffeisenbank statement evidence.

The planner has no database or workflow dependency.  It validates the posted
transaction identity against immutable parser evidence, then produces only the
high-confidence pairs that the later persistence boundary may write.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Final, Literal

from app.db.models.enums import (
    AccountType,
    ImportSource,
    TransactionClassification,
    TransactionType,
)
from app.modules.imports.raiffeisenbank import (
    STATEMENT_KIND_FIELD,
    normalize_raiffeisenbank_import_row,
)

_CURRENCY = re.compile(r"[A-Z]{3}")
_ACCOUNT_STATEMENT: Final = "account_statement"
_CARD_STATEMENT: Final = "card_statement"
_INTERNAL_ACCOUNT_TYPES: Final = frozenset({AccountType.bank, AccountType.savings})
_CASH_EXCHANGE_TYPES: Final = frozenset({"Konverze", "Vyrovnání pohledávek převodem z jiné měny"})
_CARD_REPAYMENT_TYPE: Final = "Splátka klienta"
_BANK_CARD_PAYMENT_TYPE: Final = "Jednorázová úhrada"
_CARD_SUFFIX = re.compile(r"[0-9]{4}")

ReconciliationClassification = Literal[
    TransactionClassification.internal_transfer,
    TransactionClassification.credit_card_payment,
    TransactionClassification.cash_exchange,
]


class RaiffeisenbankReconciliationEvidenceError(ValueError):
    """Raised when input evidence is malformed or yields an ambiguous match."""


@dataclass(frozen=True)
class RaiffeisenbankReconciliationAccount:
    """Immutable account metadata needed to prove a source-side relationship."""

    account_id: str
    owner_id: str
    account_type: AccountType
    currency: str


@dataclass(frozen=True)
class RaiffeisenbankPostedTransactionIdentity:
    """The immutable identity of one already-posted Raiffeisenbank transaction."""

    transaction_id: str
    account_id: str
    date: datetime
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    classification: TransactionClassification
    external_id: str | None
    source: ImportSource = ImportSource.raiffeisenbank


@dataclass(frozen=True)
class RaiffeisenbankReconciliationCandidate:
    """Posted transaction identity together with its parser-attested raw row."""

    posted: RaiffeisenbankPostedTransactionIdentity
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class RaiffeisenbankReconciliationPairPlan:
    """One deterministic, high-confidence pair without any persistence action."""

    pair_id: str
    classification: ReconciliationClassification
    from_transaction_id: str
    to_transaction_id: str
    evidence_hash: str


@dataclass(frozen=True)
class RaiffeisenbankReconciliationPlan:
    """All supported pair plans plus deterministically unpaired real movements."""

    pairs: tuple[RaiffeisenbankReconciliationPairPlan, ...]
    unpaired_transaction_ids: tuple[str, ...]
    remaining_real_income_transaction_ids: tuple[str, ...]
    remaining_real_expense_transaction_ids: tuple[str, ...]

    @property
    def paired_transaction_ids(self) -> tuple[str, ...]:
        return tuple(
            transaction_id
            for pair in self.pairs
            for transaction_id in (pair.from_transaction_id, pair.to_transaction_id)
        )


@dataclass(frozen=True)
class _ValidatedCandidate:
    candidate: RaiffeisenbankReconciliationCandidate
    account: RaiffeisenbankReconciliationAccount
    statement_kind: Literal["account_statement", "card_statement"]
    source_account_identity: str | None
    counterparty_account_identity: str | None
    provider_transaction_id: str | None
    source_type: str | None
    source_booking_time: datetime | None
    original_amount: Decimal | None
    original_currency: str | None


def plan_raiffeisenbank_reconciliation(
    *,
    accounts: Iterable[RaiffeisenbankReconciliationAccount],
    candidates: Iterable[RaiffeisenbankReconciliationCandidate],
) -> RaiffeisenbankReconciliationPlan:
    """Create order-independent plans for only three strictly evidenced pair types.

    No candidate is matched from a description, category, or fuzzy name.  A
    candidate with no strong counterpart remains unpaired.  A candidate with
    two or more strong counterparts is an evidence conflict and fails closed.
    """
    account_by_id = _validated_accounts(accounts)
    validated = _validated_candidates(candidates, account_by_id=account_by_id)
    potential = [
        *_internal_transfer_pairs(validated),
        *_credit_card_payment_pairs(validated),
        *_cash_exchange_pairs(validated),
    ]
    _require_unambiguous(potential)
    pairs = tuple(sorted(potential, key=lambda pair: pair.pair_id))
    paired_ids = {transaction_id for pair in pairs for transaction_id in _pair_ids(pair)}
    unpaired = tuple(
        sorted(transaction_id for transaction_id in validated if transaction_id not in paired_ids)
    )
    remaining_income = tuple(
        transaction_id
        for transaction_id in unpaired
        if validated[transaction_id].candidate.posted.transaction_type is TransactionType.income
    )
    remaining_expense = tuple(
        transaction_id
        for transaction_id in unpaired
        if validated[transaction_id].candidate.posted.transaction_type is TransactionType.expense
    )
    return RaiffeisenbankReconciliationPlan(
        pairs=pairs,
        unpaired_transaction_ids=unpaired,
        remaining_real_income_transaction_ids=remaining_income,
        remaining_real_expense_transaction_ids=remaining_expense,
    )


def _validated_accounts(
    accounts: Iterable[RaiffeisenbankReconciliationAccount],
) -> dict[str, RaiffeisenbankReconciliationAccount]:
    result: dict[str, RaiffeisenbankReconciliationAccount] = {}
    for account in accounts:
        _require_identifier("account ID", account.account_id)
        _require_identifier("account owner ID", account.owner_id)
        _require_currency(account.currency)
        if not isinstance(account.account_type, AccountType):
            raise RaiffeisenbankReconciliationEvidenceError("Account type is invalid.")
        if account.account_id in result:
            raise RaiffeisenbankReconciliationEvidenceError("Account IDs must be unique.")
        if account.account_type not in {
            AccountType.bank,
            AccountType.savings,
            AccountType.credit_card,
        }:
            raise RaiffeisenbankReconciliationEvidenceError(
                "Only bank, savings, and credit-card accounts are supported."
            )
        result[account.account_id] = account
    return result


def _validated_candidates(
    candidates: Iterable[RaiffeisenbankReconciliationCandidate],
    *,
    account_by_id: dict[str, RaiffeisenbankReconciliationAccount],
) -> dict[str, _ValidatedCandidate]:
    result: dict[str, _ValidatedCandidate] = {}
    for candidate in candidates:
        posted = candidate.posted
        _require_identifier("transaction ID", posted.transaction_id)
        account = account_by_id.get(posted.account_id)
        if account is None:
            raise RaiffeisenbankReconciliationEvidenceError(
                "Posted transaction does not belong to a supplied account."
            )
        if posted.transaction_id in result:
            raise RaiffeisenbankReconciliationEvidenceError("Transaction IDs must be unique.")
        _validate_raw_data(candidate.raw_data)
        normalized = normalize_raiffeisenbank_import_row(
            account_id=account.account_id,
            raw_data=candidate.raw_data,
        )
        if normalized.data is None or normalized.validation_errors is not None:
            raise RaiffeisenbankReconciliationEvidenceError(
                "Raw reconciliation evidence cannot be normalized."
            )
        _validate_posted_identity(posted=posted, normalized_data=normalized.data)
        statement_kind = candidate.raw_data[STATEMENT_KIND_FIELD]
        if statement_kind == _ACCOUNT_STATEMENT:
            validated = _validated_account_statement(candidate=candidate, account=account)
        else:
            validated = _validated_card_statement(candidate=candidate, account=account)
        result[posted.transaction_id] = validated
    return result


def _validate_raw_data(raw_data: dict[str, Any]) -> None:
    if not isinstance(raw_data, dict):
        raise RaiffeisenbankReconciliationEvidenceError(
            "Raw reconciliation evidence must be a dictionary."
        )
    statement_kind = raw_data.get(STATEMENT_KIND_FIELD)
    if statement_kind not in {_ACCOUNT_STATEMENT, _CARD_STATEMENT}:
        raise RaiffeisenbankReconciliationEvidenceError("Raiffeisenbank statement kind is invalid.")
    for field, value in raw_data.items():
        if not isinstance(field, str) or not field.strip():
            raise RaiffeisenbankReconciliationEvidenceError(
                "Raw reconciliation field names must be non-empty strings."
            )
        if field.startswith("__") and field != STATEMENT_KIND_FIELD:
            raise RaiffeisenbankReconciliationEvidenceError(
                "Raw reconciliation evidence contains parser errors."
            )
        if value is not None and not isinstance(value, str):
            raise RaiffeisenbankReconciliationEvidenceError(
                "Raw reconciliation field values must be strings or null."
            )


def _validate_posted_identity(
    *, posted: RaiffeisenbankPostedTransactionIdentity, normalized_data: dict[str, Any]
) -> None:
    if posted.source is not ImportSource.raiffeisenbank:
        raise RaiffeisenbankReconciliationEvidenceError("Posted transaction source is invalid.")
    if not isinstance(posted.date, datetime) or posted.date.tzinfo is not None:
        raise RaiffeisenbankReconciliationEvidenceError("Posted transaction date is invalid.")
    if (
        not isinstance(posted.amount, Decimal)
        or not posted.amount.is_finite()
        or posted.amount.is_zero()
    ):
        raise RaiffeisenbankReconciliationEvidenceError("Posted transaction amount is invalid.")
    _require_currency(posted.currency)
    if not isinstance(posted.transaction_type, TransactionType) or not isinstance(
        posted.classification, TransactionClassification
    ):
        raise RaiffeisenbankReconciliationEvidenceError(
            "Posted transaction classification is invalid."
        )
    expected_date = _normalized_timestamp(normalized_data["date"])
    try:
        expected_amount = Decimal(normalized_data["amount"])
    except (InvalidOperation, TypeError) as exc:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Normalized reconciliation amount is invalid."
        ) from exc
    if (
        posted.date != expected_date
        or posted.amount != expected_amount
        or posted.currency != normalized_data["currency"]
        or posted.external_id != normalized_data["external_id"]
    ):
        raise RaiffeisenbankReconciliationEvidenceError(
            "Posted transaction identity does not match normalized source evidence."
        )
    expected_type = TransactionType.income if posted.amount > 0 else TransactionType.expense
    expected_classification = (
        TransactionClassification.real_income
        if posted.amount > 0
        else TransactionClassification.real_expense
    )
    if (
        posted.transaction_type is not expected_type
        or posted.classification is not expected_classification
    ):
        raise RaiffeisenbankReconciliationEvidenceError(
            "Only unpaired real-income and real-expense transactions are eligible."
        )


def _validated_account_statement(
    *,
    candidate: RaiffeisenbankReconciliationCandidate,
    account: RaiffeisenbankReconciliationAccount,
) -> _ValidatedCandidate:
    if account.account_type not in {AccountType.bank, AccountType.savings}:
        raise RaiffeisenbankReconciliationEvidenceError(
            "An account statement cannot be assigned to a credit-card account."
        )
    raw = candidate.raw_data
    source_account = _required_raw_text(raw, "Číslo účtu")
    raw_currency = _required_raw_text(raw, "Měna účtu").upper()
    if raw_currency != account.currency:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Source account currency does not match account metadata."
        )
    original_amount, original_currency = _optional_original(raw)
    return _ValidatedCandidate(
        candidate=candidate,
        account=account,
        statement_kind=_ACCOUNT_STATEMENT,
        source_account_identity=source_account,
        counterparty_account_identity=_optional_raw_text(raw, "Číslo protiúčtu"),
        provider_transaction_id=_optional_raw_text(raw, "Id transakce"),
        source_type=_optional_raw_text(raw, "Typ transakce"),
        source_booking_time=_source_booking_time(raw, "Datum zaúčtování"),
        original_amount=original_amount,
        original_currency=original_currency,
    )


def _validated_card_statement(
    *,
    candidate: RaiffeisenbankReconciliationCandidate,
    account: RaiffeisenbankReconciliationAccount,
) -> _ValidatedCandidate:
    if account.account_type is not AccountType.credit_card:
        raise RaiffeisenbankReconciliationEvidenceError(
            "A card statement must be assigned to a credit-card account."
        )
    _required_raw_text(candidate.raw_data, "Číslo kreditní karty")
    raw_currency = _required_raw_text(candidate.raw_data, "Měna zaúčtování").upper()
    if raw_currency != account.currency:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Source card currency does not match account metadata."
        )
    return _ValidatedCandidate(
        candidate=candidate,
        account=account,
        statement_kind=_CARD_STATEMENT,
        source_account_identity=None,
        counterparty_account_identity=None,
        provider_transaction_id=None,
        source_type=_optional_raw_text(candidate.raw_data, "Typ transakce"),
        source_booking_time=_source_booking_time(candidate.raw_data, "Datum zúčtování"),
        original_amount=None,
        original_currency=None,
    )


def _internal_transfer_pairs(
    candidates: dict[str, _ValidatedCandidate],
) -> list[RaiffeisenbankReconciliationPairPlan]:
    by_provider_id: dict[str, list[_ValidatedCandidate]] = defaultdict(list)
    for candidate in candidates.values():
        if (
            candidate.statement_kind == _ACCOUNT_STATEMENT
            and candidate.account.account_type in _INTERNAL_ACCOUNT_TYPES
            and candidate.provider_transaction_id is not None
        ):
            by_provider_id[candidate.provider_transaction_id].append(candidate)
    pairs: list[RaiffeisenbankReconciliationPairPlan] = []
    for provider_id in sorted(by_provider_id):
        group = by_provider_id[provider_id]
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if _is_internal_transfer_pair(left, right):
                    pairs.append(
                        _pair_plan(
                            TransactionClassification.internal_transfer,
                            left,
                            right,
                        )
                    )
    return pairs


def _is_internal_transfer_pair(left: _ValidatedCandidate, right: _ValidatedCandidate) -> bool:
    return (
        left.account.owner_id == right.account.owner_id
        and {left.account.account_type, right.account.account_type}
        == {AccountType.bank, AccountType.savings}
        and left.account.currency == right.account.currency
        and left.source_booking_time is not None
        and left.source_booking_time == right.source_booking_time
        and left.candidate.posted.amount == -right.candidate.posted.amount
        and left.counterparty_account_identity == right.source_account_identity
        and right.counterparty_account_identity == left.source_account_identity
    )


def _credit_card_payment_pairs(
    candidates: dict[str, _ValidatedCandidate],
) -> list[RaiffeisenbankReconciliationPairPlan]:
    card_repayments = [
        candidate for candidate in candidates.values() if _is_card_repayment(candidate)
    ]
    bank_payments_by_financial_identity: dict[
        tuple[datetime, Decimal, str], list[_ValidatedCandidate]
    ] = defaultdict(list)
    for candidate in candidates.values():
        posted = candidate.candidate.posted
        if candidate.statement_kind == _ACCOUNT_STATEMENT and posted.amount < 0:
            bank_payments_by_financial_identity[
                (posted.date, -posted.amount, posted.currency)
            ].append(candidate)
    pairs: list[RaiffeisenbankReconciliationPairPlan] = []
    for card in card_repayments:
        posted = card.candidate.posted
        for bank in bank_payments_by_financial_identity[
            (posted.date, posted.amount, posted.currency)
        ]:
            if _is_credit_card_payment_pair(card, bank):
                pairs.append(
                    _pair_plan(
                        TransactionClassification.credit_card_payment,
                        card,
                        bank,
                    )
                )
    return pairs


def _is_card_repayment(candidate: _ValidatedCandidate) -> bool:
    posted = candidate.candidate.posted
    return (
        candidate.statement_kind == _CARD_STATEMENT
        and posted.amount > 0
        and candidate.source_type == _CARD_REPAYMENT_TYPE
        and _card_suffix(_required_raw_text(candidate.candidate.raw_data, "Číslo kreditní karty"))
        is not None
    )


def _is_credit_card_payment_pair(
    card: _ValidatedCandidate,
    bank: _ValidatedCandidate,
) -> bool:
    raw = bank.candidate.raw_data
    card_suffix = _card_suffix(_required_raw_text(card.candidate.raw_data, "Číslo kreditní karty"))
    assert card_suffix is not None
    variable_symbol = _optional_raw_text(raw, "VS")
    return (
        bank.account.account_type is AccountType.bank
        and bank.account.owner_id == card.account.owner_id
        and bank.source_type == _BANK_CARD_PAYMENT_TYPE
        and bank.counterparty_account_identity is not None
        and variable_symbol is not None
        and variable_symbol.isascii()
        and variable_symbol.isdecimal()
        and variable_symbol.endswith(card_suffix)
    )


def _cash_exchange_pairs(
    candidates: dict[str, _ValidatedCandidate],
) -> list[RaiffeisenbankReconciliationPairPlan]:
    eligible = [
        candidate
        for candidate in candidates.values()
        if (
            candidate.statement_kind == _ACCOUNT_STATEMENT
            and candidate.account.account_type is AccountType.bank
            and candidate.source_type in _CASH_EXCHANGE_TYPES
        )
    ]
    pairs: list[RaiffeisenbankReconciliationPairPlan] = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            if _is_cash_exchange_pair(left, right):
                pairs.append(_pair_plan(TransactionClassification.cash_exchange, left, right))
    return pairs


def _is_cash_exchange_pair(left: _ValidatedCandidate, right: _ValidatedCandidate) -> bool:
    left_posted = left.candidate.posted
    right_posted = right.candidate.posted
    return (
        left.account.owner_id == right.account.owner_id
        and left.account.account_id != right.account.account_id
        and {left.account.currency, right.account.currency} == {"CZK", "EUR"}
        and left.source_account_identity == right.source_account_identity
        and left.source_booking_time is not None
        and left.source_booking_time == right.source_booking_time
        and left_posted.date == right_posted.date
        and left_posted.amount * right_posted.amount < 0
        and left.source_type == right.source_type
        and _original_amount_corroborates(left, right)
    )


def _original_amount_corroborates(left: _ValidatedCandidate, right: _ValidatedCandidate) -> bool:
    corroborations: list[bool] = []
    if left.original_amount is not None and left.original_currency is not None:
        corroborations.append(
            left.original_currency == right.candidate.posted.currency
            and abs(left.original_amount) == abs(right.candidate.posted.amount)
        )
    if right.original_amount is not None and right.original_currency is not None:
        corroborations.append(
            right.original_currency == left.candidate.posted.currency
            and abs(right.original_amount) == abs(left.candidate.posted.amount)
        )
    return bool(corroborations) and all(corroborations)


def _pair_plan(
    classification: ReconciliationClassification,
    left: _ValidatedCandidate,
    right: _ValidatedCandidate,
) -> RaiffeisenbankReconciliationPairPlan:
    left_posted = left.candidate.posted
    right_posted = right.candidate.posted
    if left_posted.amount < 0 < right_posted.amount:
        from_candidate, to_candidate = left, right
    elif right_posted.amount < 0 < left_posted.amount:
        from_candidate, to_candidate = right, left
    else:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Reconciliation pair does not have opposing directions."
        )
    identity = {
        "schema_version": 1,
        "source": ImportSource.raiffeisenbank.value,
        "classification": classification.value,
        "transaction_ids": sorted((left_posted.transaction_id, right_posted.transaction_id)),
    }
    pair_hash = _hash(identity)
    evidence_hash = _hash(
        {
            **identity,
            "accounts": sorted(
                (_account_evidence(left.account), _account_evidence(right.account)),
                key=lambda item: item["account_id"],
            ),
            "legs": sorted(
                (_candidate_evidence(left), _candidate_evidence(right)),
                key=lambda item: item["transaction_id"],
            ),
        }
    )
    return RaiffeisenbankReconciliationPairPlan(
        pair_id=f"rb-reconciliation-{pair_hash}",
        classification=classification,
        from_transaction_id=from_candidate.candidate.posted.transaction_id,
        to_transaction_id=to_candidate.candidate.posted.transaction_id,
        evidence_hash=evidence_hash,
    )


def _require_unambiguous(pairs: Iterable[RaiffeisenbankReconciliationPairPlan]) -> None:
    by_transaction_id: dict[str, set[tuple[ReconciliationClassification, str]]] = defaultdict(set)
    pair_ids: set[str] = set()
    for pair in pairs:
        if pair.pair_id in pair_ids:
            raise RaiffeisenbankReconciliationEvidenceError(
                "The same reconciliation evidence was planned more than once."
            )
        pair_ids.add(pair.pair_id)
        for transaction_id in _pair_ids(pair):
            by_transaction_id[transaction_id].add((pair.classification, pair.pair_id))
    if any(len(matches) > 1 for matches in by_transaction_id.values()):
        raise RaiffeisenbankReconciliationEvidenceError(
            "A transaction has more than one strong reconciliation counterpart."
        )


def _pair_ids(pair: RaiffeisenbankReconciliationPairPlan) -> tuple[str, str]:
    return pair.from_transaction_id, pair.to_transaction_id


def _account_evidence(account: RaiffeisenbankReconciliationAccount) -> dict[str, Any]:
    return {
        "account_id": account.account_id,
        "owner_id": account.owner_id,
        "account_type": account.account_type.value,
        "currency": account.currency,
    }


def _candidate_evidence(candidate: _ValidatedCandidate) -> dict[str, Any]:
    posted = candidate.candidate.posted
    return {
        "transaction_id": posted.transaction_id,
        "account_id": posted.account_id,
        "date": posted.date.isoformat(),
        "amount": format(posted.amount, "f"),
        "currency": posted.currency,
        "external_id": posted.external_id,
        "raw_data": sorted(candidate.candidate.raw_data.items()),
    }


def _normalized_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise RaiffeisenbankReconciliationEvidenceError(
            "Normalized reconciliation date is invalid."
        )
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), datetime.min.time())
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Normalized reconciliation date is invalid."
        ) from exc
    if result.tzinfo is not None:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Normalized reconciliation date must be timezone-naive."
        )
    return result


def _source_booking_time(raw_data: dict[str, Any], field: str) -> datetime:
    value = _required_raw_text(raw_data, field)
    candidate = " ".join(value.split())
    for format_ in (
        "%d. %m. %Y %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d. %m. %Y %H:%M",
        "%d.%m.%Y %H:%M",
        "%d. %m. %Y",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(candidate, format_)
        except ValueError:
            continue
    raise RaiffeisenbankReconciliationEvidenceError("Raw booking time is invalid.")


def _optional_original(raw_data: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    amount = _optional_raw_text(raw_data, "Původní částka")
    currency = _optional_raw_text(raw_data, "Původní měna")
    if amount is None and currency is None:
        return None, None
    if amount is None or currency is None:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Original amount and currency must be present together."
        )
    normalized_amount = _decimal(amount)
    if normalized_amount.is_zero():
        raise RaiffeisenbankReconciliationEvidenceError("Original amount cannot be zero.")
    normalized_currency = currency.upper()
    _require_currency(normalized_currency)
    return normalized_amount, normalized_currency


def _decimal(value: str) -> Decimal:
    candidate = value.strip().replace("\u00a0", "").replace(" ", "")
    if candidate.count(",") == 1 and candidate.count(".") == 0:
        candidate = candidate.replace(",", ".")
    elif candidate.count(",") and candidate.count("."):
        if candidate.rfind(",") > candidate.rfind("."):
            candidate = candidate.replace(".", "").replace(",", ".")
        else:
            candidate = candidate.replace(",", "")
    try:
        amount = Decimal(candidate)
    except InvalidOperation as exc:
        raise RaiffeisenbankReconciliationEvidenceError("Original amount is invalid.") from exc
    if not amount.is_finite():
        raise RaiffeisenbankReconciliationEvidenceError("Original amount is invalid.")
    return amount


def _required_raw_text(raw_data: dict[str, Any], field: str) -> str:
    value = _optional_raw_text(raw_data, field)
    if value is None:
        raise RaiffeisenbankReconciliationEvidenceError(
            "Required raw reconciliation evidence is missing."
        )
    return value


def _optional_raw_text(raw_data: dict[str, Any], field: str) -> str | None:
    value = raw_data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RaiffeisenbankReconciliationEvidenceError("Raw reconciliation evidence is invalid.")
    normalized = value.strip()
    return normalized or None


def _card_suffix(value: str) -> str | None:
    digits = "".join(character for character in value if character.isdecimal())
    suffix = digits[-4:]
    return suffix if _CARD_SUFFIX.fullmatch(suffix) is not None else None


def _require_identifier(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RaiffeisenbankReconciliationEvidenceError(f"{name.capitalize()} is invalid.")


def _require_currency(value: object) -> None:
    if not isinstance(value, str) or _CURRENCY.fullmatch(value) is None:
        raise RaiffeisenbankReconciliationEvidenceError("Currency is invalid.")


def _hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
