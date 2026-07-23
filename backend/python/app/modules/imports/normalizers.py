from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from app.db.models.enums import ImportSource


@dataclass(frozen=True)
class NormalizedImportRow:
    data: dict[str, Any] | None
    deduplication_key: str | None
    validation_errors: list[dict[str, str]] | None


ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": (
        "id",
        "transaction id",
        "transaction_id",
        "id transakce",
        "reference",
        "order id",
    ),
    "date": (
        "date",
        "datum",
        "datum a čas",
        "datum a cas",
        "transaction date",
        "time",
        "timestamp",
        "created at",
    ),
    "description": (
        "description",
        "popis",
        "note",
        "merchant",
        "name",
        "instrument",
        "action",
    ),
    "amount": (
        "amount",
        "částka",
        "castka",
        "množství",
        "mnozstvi",
        "total",
        "value",
        "result",
        "quantity",
    ),
    "currency": ("currency", "měna", "mena", "currency code", "asset", "ticker"),
    "type": ("type", "typ", "transaction type", "action", "operation"),
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M:%S",
)
MAX_OPTIONAL_FIELD_LENGTH = 4096


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _lookup(raw: dict[str, Any], field: str) -> str | None:
    keyed: dict[str, list[tuple[str, Any]]] = {}
    for raw_key, value in raw.items():
        keyed.setdefault(_key(str(raw_key)), []).append((str(raw_key), value))
    for alias in ALIASES[field]:
        candidates = sorted(keyed.get(alias, ()), key=lambda item: (item[0].casefold(), item[0]))
        for _, value in candidates:
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _normalize_date(value: str) -> str:
    candidate = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError as exc:
            raise ValueError("Unsupported date format.") from exc
    try:
        parsed_iso = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        if parsed_iso.tzinfo is not None:
            parsed_iso = parsed_iso.astimezone(UTC)
        return parsed_iso.isoformat()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)
            if parsed.time() == datetime.min.time():
                return date(parsed.year, parsed.month, parsed.day).isoformat()
            return parsed.isoformat()
        except ValueError:
            continue
    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", candidate)
    if slash_match:
        first, second, year = (int(part) for part in slash_match.groups())
        if first <= 12 and second <= 12:
            raise ValueError("Ambiguous slash date format.")
        day, month = (first, second) if first > 12 else (second, first)
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ValueError("Unsupported date format.") from exc
    raise ValueError("Unsupported date format.")


def _normalize_amount(value: str) -> str:
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
        raise ValueError("Invalid decimal amount.") from exc
    if not amount.is_finite():
        raise ValueError("Amount must be finite.")
    return format(amount.normalize(), "f")


def _deduplication_key(*, source: ImportSource, account_id: str, data: dict[str, Any]) -> str:
    # This is candidate duplicate identity only. Posting may use it for review, but Step 5D
    # never suppresses rows; optional provider text intentionally remains identity-sensitive.
    identity = {
        "source": source.value,
        "account_id": account_id,
        "external_id": data.get("external_id"),
        "date": data["date"],
        "amount": data["amount"],
        "currency": data["currency"],
        "description": data.get("description", ""),
        "type": data.get("type", ""),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def normalize_import_row(
    *, source: ImportSource, account_id: str, raw_data: dict[str, Any]
) -> NormalizedImportRow:
    if source is ImportSource.trading212:
        # Imported lazily so the provider module can reuse this stable result contract.
        from app.modules.imports.trading212 import normalize_trading212_import_row

        return normalize_trading212_import_row(account_id=account_id, raw_data=raw_data)

    errors: list[dict[str, str]] = []
    raw_date = _lookup(raw_data, "date")
    raw_amount = _lookup(raw_data, "amount")
    raw_currency = _lookup(raw_data, "currency")

    if raw_date is None:
        errors.append({"field": "date", "code": "required", "message": "Date is required."})
    if raw_amount is None:
        errors.append({"field": "amount", "code": "required", "message": "Amount is required."})
    if raw_currency is None:
        errors.append({"field": "currency", "code": "required", "message": "Currency is required."})

    normalized_date: str | None = None
    normalized_amount: str | None = None
    if raw_date is not None:
        try:
            normalized_date = _normalize_date(raw_date)
        except ValueError as exc:
            errors.append({"field": "date", "code": "invalid", "message": str(exc)})
    if raw_amount is not None:
        try:
            normalized_amount = _normalize_amount(raw_amount)
        except ValueError as exc:
            errors.append({"field": "amount", "code": "invalid", "message": str(exc)})

    currency = raw_currency.upper() if raw_currency else None
    if currency is not None and not re.fullmatch(r"[A-Z0-9._-]{2,20}", currency):
        errors.append({"field": "currency", "code": "invalid", "message": "Currency is invalid."})

    optional_values: dict[str, str] = {}
    for field in ("external_id", "description", "type"):
        value = _lookup(raw_data, field)
        if value is None:
            continue
        if len(value) > MAX_OPTIONAL_FIELD_LENGTH:
            errors.append(
                {
                    "field": field,
                    "code": "too_long",
                    "message": f"{field.replace('_', ' ').title()} is too long.",
                }
            )
        else:
            optional_values[field] = value

    if errors:
        return NormalizedImportRow(data=None, deduplication_key=None, validation_errors=errors)

    assert normalized_date is not None
    assert normalized_amount is not None
    assert currency is not None
    data: dict[str, Any] = {
        "schema_version": 1,
        "source": source.value,
        "date": normalized_date,
        "amount": normalized_amount,
        "currency": currency,
        **optional_values,
    }
    return NormalizedImportRow(
        data=data,
        deduplication_key=_deduplication_key(source=source, account_id=account_id, data=data),
        validation_errors=None,
    )
