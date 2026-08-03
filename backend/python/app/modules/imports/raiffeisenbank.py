"""Raiffeisenbank-specific CSV parsing and canonical row normalization."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
from typing import Any, Final, Literal

from app.db.models.enums import ImportSource
from app.modules.imports.normalizers import (
    MAX_OPTIONAL_FIELD_LENGTH,
    NormalizedImportRow,
    _normalize_amount,
)
from app.modules.imports.parsers import (
    ImportParseError,
    ParsedImportRow,
    _decode,
    _delimiter,
    parse_csv,
)

StatementKind = Literal["account_statement", "card_statement"]

STATEMENT_KIND_FIELD: Final = "__raiffeisenbank_statement_kind"

_ACCOUNT_REQUIRED: Final = frozenset(
    {
        "Datum provedení",
        "Zaúčtovaná částka",
        "Měna účtu",
    }
)
_CARD_REQUIRED: Final = frozenset(
    {
        "Datum transakce",
        "Zaúčtovaná částka",
        "Měna zaúčtování",
    }
)
_ACCOUNT_MARKERS: Final = frozenset(
    {"Datum provedení", "Měna účtu", "Název protiúčtu", "Id transakce"}
)
_CARD_MARKERS: Final = frozenset(
    {"Datum transakce", "Měna zaúčtování", "Číslo kreditní karty", "Název Obchodníka"}
)
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_CARD_SUFFIX_PATTERN = re.compile(r"[0-9A-Za-z]")

_DATE_FORMATS: Final[tuple[tuple[str, bool], ...]] = (
    ("%d. %m. %Y", False),
    ("%d.%m.%Y", False),
    ("%d. %m. %Y %H:%M", True),
    ("%d.%m.%Y %H:%M", True),
    ("%d. %m. %Y %H:%M:%S", True),
    ("%d.%m.%Y %H:%M:%S", True),
)

_ACCOUNT_FIELDS: Final = {
    "date": "Datum provedení",
    "amount": "Zaúčtovaná částka",
    "currency": "Měna účtu",
    "type": "Typ transakce",
    "counterparty": "Název protiúčtu",
    "external_id": "Id transakce",
}
_CARD_FIELDS: Final = {
    "date": "Datum transakce",
    "amount": "Zaúčtovaná částka",
    "currency": "Měna zaúčtování",
    "type": "Typ transakce",
    "counterparty": "Název Obchodníka",
    "card_number": "Číslo kreditní karty",
}
_ACCOUNT_DESCRIPTION_FIELDS: Final = ("Zpráva", "Poznámka", "Vlastní poznámka")
_CARD_DESCRIPTION_FIELDS: Final = (
    "Popis/Místo transakce",
    "Název Obchodníka",
    "Město",
    "Vlastní poznámka",
    "Typ transakce",
)


def _detect_statement_kind(content: bytes, encoding: str | None) -> StatementKind:
    text = _decode(content, encoding)
    if not text.strip():
        raise ImportParseError("The import file is empty.")
    delimiter = _delimiter(text)
    try:
        header = next(csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except (StopIteration, csv.Error) as exc:
        raise ImportParseError("The import file contains a malformed header row.") from exc

    normalized = tuple(value.strip() for value in header)
    if (
        not normalized
        or any(not value for value in normalized)
        or len(set(normalized)) != len(normalized)
        or STATEMENT_KIND_FIELD in normalized
    ):
        raise ImportParseError(
            "The import file does not contain a supported Raiffeisenbank header."
        )

    fields = frozenset(normalized)
    is_account = _ACCOUNT_REQUIRED <= fields
    is_card = _CARD_REQUIRED <= fields
    has_account_markers = bool(fields & _ACCOUNT_MARKERS)
    has_card_markers = bool(fields & _CARD_MARKERS)

    if (is_account and has_card_markers) or (is_card and has_account_markers):
        raise ImportParseError("The import file contains an ambiguous Raiffeisenbank header.")
    if is_account and not is_card:
        return "account_statement"
    if is_card and not is_account:
        return "card_statement"
    if is_account or is_card or (has_account_markers and has_card_markers):
        raise ImportParseError("The import file contains an ambiguous Raiffeisenbank header.")
    raise ImportParseError("The import file does not contain a supported Raiffeisenbank header.")


def parse_raiffeisenbank_csv(
    content: bytes,
    *,
    encoding: str | None,
) -> list[ParsedImportRow]:
    """Detect one supported statement shape and preserve every physical data row."""
    statement_kind = _detect_statement_kind(content, encoding)
    rows = parse_csv(content, encoding=encoding)
    return [
        replace(
            row,
            raw_data={
                **row.raw_data,
                STATEMENT_KIND_FIELD: statement_kind,
            },
        )
        for row in rows
    ]


def _text(raw_data: dict[str, Any], field: str) -> str | None:
    value = raw_data.get(field)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalized_date(value: str) -> str:
    candidate = " ".join(value.strip().split())
    for date_format, has_time in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, date_format)
        except ValueError:
            continue
        return (
            parsed.isoformat()
            if has_time
            else date(parsed.year, parsed.month, parsed.day).isoformat()
        )
    raise ValueError("Unsupported Raiffeisenbank date format.")


def _description(raw_data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    values: list[str] = []
    seen: set[str] = set()
    for field in fields:
        value = _text(raw_data, field)
        if value is None or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return " | ".join(values) or None


def _bounded(
    *,
    field: str,
    value: str | None,
    errors: list[dict[str, str]],
) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_OPTIONAL_FIELD_LENGTH:
        return value
    errors.append(
        {
            "field": field,
            "code": "too_long",
            "message": f"{field.replace('_', ' ').title()} is too long.",
        }
    )
    return None


def _card_suffix(raw_data: dict[str, Any]) -> str | None:
    card_number = _text(raw_data, _CARD_FIELDS["card_number"])
    if card_number is None:
        return None
    characters = "".join(_CARD_SUFFIX_PATTERN.findall(card_number))
    return characters[-4:] or None


def _fallback_external_id(
    *,
    account_id: str,
    statement_kind: StatementKind,
    normalized_date: str,
    amount: str,
    currency: str,
    source_type: str | None,
    counterparty: str | None,
    description: str | None,
    card_suffix: str | None,
) -> str:
    identity = {
        "source": ImportSource.raiffeisenbank.value,
        "account_id": account_id,
        "statement_kind": statement_kind,
        "date": normalized_date,
        "amount": amount,
        "currency": currency,
        "source_type": source_type,
        "counterparty": counterparty,
        "description": description,
        "card_suffix": card_suffix,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"rb-sha256-{sha256(encoded.encode('utf-8')).hexdigest()}"


def _deduplication_key(*, account_id: str, external_id: str) -> str:
    identity = {
        "source": ImportSource.raiffeisenbank.value,
        "account_id": account_id,
        "external_id": external_id,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def normalize_raiffeisenbank_import_row(
    *,
    account_id: str,
    raw_data: dict[str, Any],
) -> NormalizedImportRow:
    """Normalize one already format-verified Raiffeisenbank source row."""
    statement_kind_value = raw_data.get(STATEMENT_KIND_FIELD)
    if statement_kind_value not in {"account_statement", "card_statement"}:
        return NormalizedImportRow(
            data=None,
            deduplication_key=None,
            validation_errors=[
                {
                    "field": "statement_kind",
                    "code": "invalid",
                    "message": "Raiffeisenbank statement kind is invalid.",
                }
            ],
        )
    statement_kind: StatementKind = statement_kind_value
    fields = _ACCOUNT_FIELDS if statement_kind == "account_statement" else _CARD_FIELDS
    description_fields = (
        _ACCOUNT_DESCRIPTION_FIELDS
        if statement_kind == "account_statement"
        else _CARD_DESCRIPTION_FIELDS
    )
    errors: list[dict[str, str]] = []

    raw_date = _text(raw_data, fields["date"])
    raw_amount = _text(raw_data, fields["amount"])
    raw_currency = _text(raw_data, fields["currency"])
    if raw_date is None:
        errors.append({"field": "date", "code": "required", "message": "Date is required."})
    if raw_amount is None:
        errors.append({"field": "amount", "code": "required", "message": "Amount is required."})
    if raw_currency is None:
        errors.append({"field": "currency", "code": "required", "message": "Currency is required."})

    normalized_date: str | None = None
    amount: str | None = None
    if raw_date is not None:
        try:
            normalized_date = _normalized_date(raw_date)
        except ValueError as exc:
            errors.append({"field": "date", "code": "invalid", "message": str(exc)})
    if raw_amount is not None:
        try:
            amount = _normalize_amount(raw_amount)
        except ValueError as exc:
            errors.append({"field": "amount", "code": "invalid", "message": str(exc)})

    currency = raw_currency.upper() if raw_currency is not None else None
    if currency is not None and _CURRENCY_PATTERN.fullmatch(currency) is None:
        errors.append(
            {
                "field": "currency",
                "code": "invalid",
                "message": "Currency must contain exactly three uppercase ASCII letters.",
            }
        )

    source_type = _bounded(
        field="type",
        value=_text(raw_data, fields["type"]),
        errors=errors,
    )
    description = _bounded(
        field="description",
        value=_description(raw_data, description_fields),
        errors=errors,
    )
    counterparty = _bounded(
        field="counterparty",
        value=_text(raw_data, fields["counterparty"]),
        errors=errors,
    )
    if statement_kind == "card_statement" and counterparty is None:
        counterparty = _bounded(
            field="counterparty",
            value=_text(raw_data, "Popis/Místo transakce"),
            errors=errors,
        )
    provider_external_id = (
        _bounded(
            field="external_id",
            value=_text(raw_data, fields["external_id"]),
            errors=errors,
        )
        if statement_kind == "account_statement"
        else None
    )

    if errors:
        return NormalizedImportRow(data=None, deduplication_key=None, validation_errors=errors)

    assert normalized_date is not None
    assert amount is not None
    assert currency is not None
    external_id = provider_external_id or _fallback_external_id(
        account_id=account_id,
        statement_kind=statement_kind,
        normalized_date=normalized_date,
        amount=amount,
        currency=currency,
        source_type=source_type,
        counterparty=counterparty,
        description=description,
        card_suffix=_card_suffix(raw_data),
    )
    data: dict[str, Any] = {
        "schema_version": 1,
        "source": ImportSource.raiffeisenbank.value,
        "date": normalized_date,
        "amount": amount,
        "currency": currency,
        "external_id": external_id,
    }
    if description is not None:
        data["description"] = description
    if counterparty is not None:
        data["counterparty"] = counterparty
    if source_type is not None:
        data["type"] = source_type
    return NormalizedImportRow(
        data=data,
        deduplication_key=_deduplication_key(account_id=account_id, external_id=external_id),
        validation_errors=None,
    )
