"""Pure, source-specific canonicalization for Trading212 CSV rows."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from app.db.models.enums import ImportSource
from app.modules.imports.normalizers import (
    MAX_OPTIONAL_FIELD_LENGTH,
    NormalizedImportRow,
    _normalize_amount,
    _normalize_date,
)

_CURRENCY = re.compile(r"[A-Z0-9._-]{2,20}")
_ACTION = {
    "buy": "buy",
    "purchase": "buy",
    "market buy": "buy",
    "limit buy": "buy",
    "stop buy": "buy",
    "crypto purchase": "buy",
    "sell": "sell",
    "sale": "sell",
    "market sell": "sell",
    "limit sell": "sell",
    "stop sell": "sell",
    "stop loss": "sell",
    "take profit": "sell",
    "crypto sale": "sell",
    "dividend": "dividend",
    "dividends": "dividend",
    "dividend (dividend)": "dividend",
    "dividend (dividend manufactured payment)": "dividend",
    "dividend (tax exempted)": "dividend",
    "dividend reinvestment": "dividend",
    "interest": "interest",
    "interest on cash": "interest",
    "cash interest": "interest",
    "savings interest": "interest",
    "earn interest": "interest",
    "lending interest": "interest",
    "spending cashback": "interest",
    "deposit": "cash_deposit",
    "fiat deposit": "cash_deposit",
    "crypto deposit": "cash_deposit",
    "top up": "cash_deposit",
    "funding": "cash_deposit",
    "withdrawal": "cash_withdrawal",
    "fiat withdrawal": "cash_withdrawal",
    "crypto withdrawal": "cash_withdrawal",
    "currency conversion": "currency_conversion",
    "fx conversion": "currency_conversion",
    "exchange": "currency_conversion",
    "convert": "currency_conversion",
    "swap": "currency_conversion",
    "asset transfer": "asset_transfer",
    "internal transfer": "asset_transfer",
    "portfolio transfer": "asset_transfer",
    "fee": "fee",
    "commission": "fee",
    "currency conversion fee": "fee",
    "transaction fee": "fee",
    "trading fee": "fee",
    "withdrawal fee": "fee",
    "service fee": "fee",
    "staking": "staking_reward",
    "staking reward": "staking_reward",
    "staking income": "staking_reward",
    "eth2 staking reward": "staking_reward",
    "airdrop": "airdrop",
    "fork": "airdrop",
    "token distribution": "airdrop",
}
_PROMOTIONAL = frozenset(
    {
        "free share",
        "free shares",
        "free stock",
        "free stocks",
        "bonus share",
        "bonus shares",
        "bonus stock",
        "bonus stocks",
        "referral share",
        "referral shares",
        "promo share",
        "promo shares",
        "promotion share",
        "promotion shares",
    }
)
_LINKED_CASH = frozenset({"card debit", "card cost", "new card cost"})
_FEE_FIELDS = (
    ("Currency conversion fee", "Currency (Currency conversion fee)"),
    ("Stamp duty reserve tax", "Currency (Stamp duty reserve tax)"),
    ("French transaction tax", "Currency (French transaction tax)"),
    ("Finra fee", "Currency (Finra fee)"),
)


def _key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _value(raw: dict[str, Any], *aliases: str) -> str | None:
    wanted = {_key(alias) for alias in aliases}
    candidates = sorted(
        ((str(key), value) for key, value in raw.items() if _key(key) in wanted),
        key=lambda item: (item[0].casefold(), item[0]),
    )
    for _, value in candidates:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _optional(
    raw: dict[str, Any], errors: list[dict[str, str]], field: str, *aliases: str
) -> str | None:
    value = _value(raw, *aliases)
    if value is not None and len(value) > MAX_OPTIONAL_FIELD_LENGTH:
        errors.append(
            {
                "field": field,
                "code": "too_long",
                "message": f"{field.replace('_', ' ').title()} is too long.",
            }
        )
        return None
    return value


def _currency(
    value: str | None, errors: list[dict[str, str]], field: str, *, required: bool = False
) -> str | None:
    if value is None:
        if required:
            errors.append(
                {
                    "field": field,
                    "code": "required",
                    "message": f"{field.replace('_', ' ').title()} is required.",
                }
            )
        return None
    result = value.upper()
    if _CURRENCY.fullmatch(result) is None:
        errors.append({"field": field, "code": "invalid", "message": "Currency is invalid."})
        return None
    return result


def _decimal(
    value: str | None,
    errors: list[dict[str, str]],
    field: str,
    *,
    required: bool = False,
    positive: bool = False,
) -> str | None:
    if value is None:
        if required:
            errors.append(
                {
                    "field": field,
                    "code": "required",
                    "message": f"{field.replace('_', ' ').title()} is required.",
                }
            )
        return None
    try:
        result = Decimal(_normalize_amount(value))
    except (InvalidOperation, ValueError):
        errors.append(
            {"field": field, "code": "invalid", "message": "A finite decimal amount is required."}
        )
        return None
    if positive and result.copy_abs() <= 0:
        errors.append(
            {
                "field": field,
                "code": "positive_required",
                "message": "A positive amount is required.",
            }
        )
        return None
    return (
        format(result.copy_abs().normalize(), "f") if positive else format(result.normalize(), "f")
    )


def _money(
    raw: dict[str, Any],
    errors: list[dict[str, str]],
    field: str,
    amount_aliases: tuple[str, ...],
    currency_aliases: tuple[str, ...],
    *,
    required: bool = False,
    positive: bool = False,
) -> dict[str, str] | None:
    amount = _decimal(
        _value(raw, *amount_aliases),
        errors,
        f"{field}.amount",
        required=required,
        positive=positive,
    )
    currency = _currency(
        _value(raw, *currency_aliases), errors, f"{field}.currency", required=required
    )
    if (amount is None) != (currency is None) and not required:
        errors.append(
            {
                "field": field,
                "code": "paired_required",
                "message": "Amount and currency must be provided together.",
            }
        )
    return (
        {"amount": amount, "currency": currency}
        if amount is not None and currency is not None
        else None
    )


def _deduplication_key(account_id: str, data: dict[str, Any]) -> str:
    external_id = data.get("external_id")
    identity: dict[str, Any] = {"account_id": account_id, "source": ImportSource.trading212.value}
    if external_id:
        identity["external_id"] = external_id
    else:
        asset = data["asset"]
        identity.update(
            {
                "date": data["date"],
                "action": data["action"],
                "asset": {"symbol": asset["symbol"], "isin": asset["isin"]},
                "quantity": data["quantity"],
                "total": data["total"],
                "conversion": data["conversion"],
            }
        )
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def normalize_trading212_import_row(
    *, account_id: str, raw_data: dict[str, Any]
) -> NormalizedImportRow:
    """Create schema-v2 data or structured review errors without I/O."""
    errors: list[dict[str, str]] = []
    raw_action = _optional(raw_data, errors, "raw_action", "Action")
    action_token = _key(raw_action) if raw_action else None
    promotional = action_token in _PROMOTIONAL
    if action_token in _LINKED_CASH:
        errors.append(
            {
                "field": "action",
                "code": "unsupported_linked_cash_transaction",
                "message": "Linked cash card transactions require review.",
            }
        )
    action = "airdrop" if promotional else _ACTION.get(action_token or "")
    if action is None:
        errors.append(
            {
                "field": "action",
                "code": "unsupported_action",
                "message": "The Trading212 action is not supported.",
            }
        )

    raw_date = _value(raw_data, "Time", "Time UTC", "Time (UTC)")
    if raw_date is None:
        errors.append({"field": "date", "code": "required", "message": "Date is required."})
        normalized_date = None
    else:
        try:
            normalized_date = _normalize_date(raw_date)
        except ValueError:
            errors.append(
                {"field": "date", "code": "invalid", "message": "Date format is invalid."}
            )
            normalized_date = None

    symbol = _optional(raw_data, errors, "asset.symbol", "Ticker")
    if symbol:
        symbol = symbol.upper()
    isin = _optional(raw_data, errors, "asset.isin", "ISIN")
    name = _optional(raw_data, errors, "asset.name", "Name", "Merchant", "Merchant name")
    hint = _optional(raw_data, errors, "asset.asset_type_hint", "Asset type", "Asset Type")
    asset = {
        "symbol": symbol,
        "isin": isin,
        "name": name,
        "asset_type_hint": hint.casefold() if hint else None,
    }
    quantity = _decimal(_value(raw_data, "No. of shares", "Quantity"), errors, "quantity")
    price = _money(
        raw_data,
        errors,
        "price",
        ("Price / share", "Price per share", "Price"),
        ("Currency (Price / share)", "Currency (Price)", "Price currency"),
        positive=True,
    )
    total = _money(
        raw_data,
        errors,
        "total",
        ("Total", "Amount"),
        ("Currency (Total)", "Currency (Amount)", "Currency"),
        positive=True,
    )
    realized_pnl = _money(
        raw_data,
        errors,
        "realized_pnl",
        ("Result", "Realized P/L"),
        ("Currency (Result)", "Currency (Realized P/L)"),
    )
    exchange_rate = _decimal(
        _value(raw_data, "Exchange rate", "Exchange Rate"),
        errors,
        "conversion.exchange_rate",
        positive=True,
    )
    conversion = _conversion(raw_data, errors, exchange_rate)
    fee = None if promotional else _fees(raw_data, errors)
    external_id = _optional(raw_data, errors, "external_id", "ID", "Transaction ID")
    note = _optional(
        raw_data, errors, "note", "Notes", "Note", "Category", "Merchant category", "Card category"
    )

    _validate_action(action, asset, quantity, price, total, conversion, errors)
    if errors:
        return NormalizedImportRow(data=None, deduplication_key=None, validation_errors=errors)
    assert normalized_date is not None and action is not None
    data: dict[str, Any] = {
        "schema_version": 2,
        "source": ImportSource.trading212.value,
        "kind": "investment_event",
        "date": normalized_date,
        "action": action,
        "external_id": external_id,
        "raw_action": raw_action,
        "asset": asset,
        "quantity": quantity,
        "price": price,
        "total": total,
        "fee": fee,
        "conversion": conversion,
        "realized_pnl": realized_pnl,
        "is_promotional": promotional,
        "note": note,
    }
    return NormalizedImportRow(
        data=data, deduplication_key=_deduplication_key(account_id, data), validation_errors=None
    )


def _fees(raw: dict[str, Any], errors: list[dict[str, str]]) -> dict[str, str] | None:
    values: list[Decimal] = []
    currencies: set[str] = set()
    for amount_header, currency_header in _FEE_FIELDS:
        raw_amount = _value(raw, amount_header)
        if raw_amount is None:
            continue
        amount = _decimal(raw_amount, errors, "fee.amount")
        if amount is None:
            continue
        if Decimal(amount).is_zero():
            # Provider exports may contain placeholder zero-fee columns. They do not
            # establish a canonical fee section and do not need a fee currency.
            continue
        currency = _currency(_value(raw, currency_header), errors, "fee.currency")
        if currency is None:
            errors.append(
                {
                    "field": "fee.currency",
                    "code": "required",
                    "message": "Fee currency is required.",
                }
            )
            continue
        values.append(Decimal(amount).copy_abs())
        currencies.add(currency)
    if not values:
        return None
    if len(currencies) != 1:
        errors.append(
            {
                "field": "fee.currency",
                "code": "conflicting_currency",
                "message": "Fee currencies conflict.",
            }
        )
        return None
    total = sum(values, Decimal("0"))
    return {"amount": format(total.normalize(), "f"), "currency": next(iter(currencies))}


def _conversion(
    raw: dict[str, Any], errors: list[dict[str, str]], exchange_rate: str | None
) -> dict[str, Any] | None:
    from_leg = _money(
        raw,
        errors,
        "conversion.from",
        ("Currency conversion from amount",),
        ("Currency (Currency conversion from amount)",),
        positive=True,
    )
    to_leg = _money(
        raw,
        errors,
        "conversion.to",
        ("Currency conversion to amount",),
        ("Currency (Currency conversion to amount)",),
        positive=True,
    )
    if from_leg is None and to_leg is None:
        if exchange_rate is not None:
            errors.append(
                {
                    "field": "conversion",
                    "code": "paired_required",
                    "message": "Exchange rate requires conversion legs.",
                }
            )
        return None
    if from_leg is None or to_leg is None:
        errors.append(
            {
                "field": "conversion",
                "code": "paired_required",
                "message": "Both conversion legs are required.",
            }
        )
        return None
    if from_leg["currency"] == to_leg["currency"]:
        errors.append(
            {
                "field": "conversion",
                "code": "conflicting_currency",
                "message": "Conversion currencies must differ.",
            }
        )
    return {"from": from_leg, "to": to_leg, "exchange_rate": exchange_rate}


def _validate_action(
    action: str | None,
    asset: dict[str, str | None],
    quantity: str | None,
    price: dict[str, str] | None,
    total: dict[str, str] | None,
    conversion: dict[str, Any] | None,
    errors: list[dict[str, str]],
) -> None:
    def asset_required() -> None:
        if not asset["symbol"] and not asset["isin"]:
            errors.append(
                {"field": "asset", "code": "required", "message": "Asset identity is required."}
            )

    def quantity_required() -> None:
        if quantity is None or Decimal(quantity) <= 0:
            errors.append(
                {
                    "field": "quantity",
                    "code": "positive_required",
                    "message": "A positive quantity is required.",
                }
            )

    def total_required() -> None:
        if total is None or Decimal(total["amount"]) <= 0:
            errors.append(
                {
                    "field": "total",
                    "code": "positive_required",
                    "message": "A positive total is required.",
                }
            )

    if action in {"buy", "sell"}:
        asset_required()
        quantity_required()
        total_required()
        if price is not None and Decimal(price["amount"]) <= 0:
            errors.append(
                {
                    "field": "price",
                    "code": "positive_required",
                    "message": "Price must be positive.",
                }
            )
    elif action == "dividend":
        asset_required()
        total_required()
    elif action in {"interest", "cash_deposit", "cash_withdrawal", "fee"}:
        total_required()
    elif action in {"asset_transfer", "staking_reward", "airdrop"}:
        asset_required()
        quantity_required()
    elif action == "currency_conversion" and conversion is None:
        errors.append(
            {"field": "conversion", "code": "required", "message": "Conversion legs are required."}
        )
