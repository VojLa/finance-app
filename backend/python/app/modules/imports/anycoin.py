"""Deterministic, batch-scoped Anycoin normalization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from app.db.models.enums import ImportRowStatus
from app.modules.imports.normalizers import (
    MAX_OPTIONAL_FIELD_LENGTH,
    _normalize_amount,
    _normalize_date,
)

_FIAT = frozenset({"CZK", "EUR", "USD", "GBP"})
_GROUPED = {"trade payment": "payment", "trade fill": "fill", "trade refund": "refund"}
_NEUTRAL = frozenset(
    {"payment block", "payment block refund", "withdrawal_block", "withdrawal_unblock"}
)
_CURRENCY = re.compile(r"[A-Z0-9._-]{2,20}")


@dataclass(frozen=True)
class AnycoinBatchRow:
    row_id: str
    row_number: int
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class AnycoinRowOutcome:
    row_id: str
    status: ImportRowStatus
    data: dict[str, Any] | None
    deduplication_key: str | None
    validation_errors: list[dict[str, str]] | None


@dataclass(frozen=True)
class _Parsed:
    row: AnycoinBatchRow
    role: str | None
    kind: str
    order_id: str | None
    date: str | None
    amount: Decimal | None
    currency: str | None
    external_id: str | None
    invalid: bool


def _text(raw: dict[str, Any], *aliases: str) -> str | None:
    wanted = {" ".join(alias.strip().casefold().split()) for alias in aliases}
    values = sorted(
        (
            (str(k), v)
            for k, v in raw.items()
            if " ".join(str(k).strip().casefold().split()) in wanted
        ),
        key=lambda item: (item[0].casefold(), item[0]),
    )
    for _, value in values:
        if value is not None and str(value).strip():
            candidate = str(value).strip()
            return candidate if len(candidate) <= MAX_OPTIONAL_FIELD_LENGTH else None
    return None


def _parse(row: AnycoinBatchRow) -> _Parsed:
    raw_type = _text(row.raw_data, "Type", "Operation", "Transaction type")
    kind = " ".join(raw_type.casefold().split()) if raw_type else ""
    order_id = _text(row.raw_data, "Order ID", "Order id", "OrderId", "Order")
    raw_date = _text(row.raw_data, "Date", "Time", "Created at")
    raw_amount = _text(row.raw_data, "Amount", "Quantity")
    raw_currency = _text(row.raw_data, "Currency", "Asset")
    date = amount = currency = None
    invalid = False
    try:
        date = _normalize_date(raw_date) if raw_date else None
    except ValueError:
        invalid = True
    try:
        amount = Decimal(_normalize_amount(raw_amount)) if raw_amount else None
    except (InvalidOperation, ValueError):
        invalid = True
    if raw_currency:
        currency = raw_currency.upper()
        if _CURRENCY.fullmatch(currency) is None:
            invalid = True
    else:
        invalid = True
    if date is None or amount is None or currency is None:
        invalid = True
    return _Parsed(
        row,
        _GROUPED.get(kind),
        kind,
        order_id,
        date,
        amount,
        currency,
        _text(row.raw_data, "anycoin TX ID", "Transaction ID", "TX ID"),
        invalid,
    )


def _error(code: str) -> list[dict[str, str]]:
    return [{"field": "normalized_data", "code": code, "message": "Anycoin row requires review."}]


def _review(rows: list[_Parsed], code: str) -> list[AnycoinRowOutcome]:
    return [
        AnycoinRowOutcome(row.row.row_id, ImportRowStatus.needs_review, None, None, _error(code))
        for row in rows
    ]


def _marker(
    row: _Parsed, kind: str, order_id: str | None = None, anchor: str | None = None
) -> AnycoinRowOutcome:
    data: dict[str, Any] = {"schema_version": 2, "source": "anycoin", "kind": kind}
    if order_id is not None:
        data["order_id"] = order_id
    if anchor is not None:
        data["anchor_row_id"] = anchor
        data["member_role"] = row.role
    return AnycoinRowOutcome(row.row.row_id, ImportRowStatus.skipped, data, None, None)


def _decimal(value: Decimal) -> str:
    return format(value.copy_abs().normalize(), "f")


def _key(account_id: str, identity: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"account_id": account_id, "source": "anycoin", **identity},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode()).hexdigest()


def _external(rows: list[_Parsed], order_id: str, asset_currency: str) -> str | None:
    levels = [
        [
            r.external_id
            for r in rows
            if r.role == "fill" and r.currency == asset_currency and r.external_id
        ],
        [r.external_id for r in rows if r.role == "fill" and r.external_id],
        [r.external_id for r in rows if r.role in {"payment", "refund"} and r.external_id],
    ]
    for values in levels:
        unique = set(values)
        if len(unique) > 1:
            return None
        if unique:
            return next(iter(unique))
    return order_id


def normalize_anycoin_batch(
    *, account_id: str, rows: list[AnycoinBatchRow]
) -> list[AnycoinRowOutcome]:
    parsed = [_parse(row) for row in rows]
    outcomes: list[AnycoinRowOutcome] = []
    groups: dict[str, list[_Parsed]] = {}
    for row in parsed:
        if row.kind in _GROUPED:
            if not row.order_id:
                outcomes.extend(_review([row], "missing_order_id"))
            else:
                groups.setdefault(row.order_id, []).append(row)
        elif row.kind in {"deposit", "withdrawal"}:
            outcomes.extend(_standalone(account_id, row))
        elif row.kind in _NEUTRAL:
            outcomes.append(_marker(row, "neutral_row"))
        else:
            outcomes.extend(_review([row], "unsupported_anycoin_row"))
    for order_id in sorted(groups):
        outcomes.extend(_group(account_id, order_id, groups[order_id]))
    return sorted(outcomes, key=lambda item: item.row_id)


def _standalone(account_id: str, row: _Parsed) -> list[AnycoinRowOutcome]:
    if (
        row.invalid
        or row.amount is None
        or row.amount.is_zero()
        or row.currency is None
        or row.date is None
    ):
        return _review([row], "invalid_anycoin_row")
    if row.currency in _FIAT:
        return _review([row], "unsupported_anycoin_fiat_transfer")
    direction = "in" if row.kind == "deposit" else "out"
    payload = {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "investment_event",
        "date": row.date,
        "action": "asset_transfer",
        "external_id": row.external_id,
        "order_id": None,
        "raw_action": row.kind,
        "asset": {"symbol": row.currency, "isin": None, "name": None, "asset_type_hint": "crypto"},
        "quantity": _decimal(row.amount),
        "price": None,
        "total": None,
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "asset_direction": direction,
    }
    identity = (
        {"external_id": row.external_id}
        if row.external_id
        else {
            "date": row.date,
            "action": "asset_transfer",
            "symbol": row.currency,
            "quantity": payload["quantity"],
            "direction": direction,
        }
    )
    return [
        AnycoinRowOutcome(
            row.row.row_id, ImportRowStatus.pending, payload, _key(account_id, identity), None
        )
    ]


def _group(account_id: str, order_id: str, rows: list[_Parsed]) -> list[AnycoinRowOutcome]:
    if any(row.invalid or row.amount is None or row.amount.is_zero() for row in rows):
        return _review(rows, "invalid_anycoin_row")
    payments = [r for r in rows if r.role == "payment"]
    fills = [r for r in rows if r.role == "fill"]
    refunds = [r for r in rows if r.role == "refund"]
    nets: dict[str, Decimal] = {}
    for row in rows:
        assert row.currency is not None and row.amount is not None
        nets[row.currency] = nets.get(row.currency, Decimal("0")) + row.amount
    if payments and refunds and not fills and all(net == 0 for net in nets.values()):
        return [_marker(row, "fully_refunded_group", order_id) for row in rows]
    if not payments or not fills:
        return _review(rows, "incomplete_order")
    assets = {currency for currency in nets if currency not in _FIAT}
    fiats = {currency for currency in nets if currency in _FIAT}
    if len(assets) != 1:
        return _review(rows, "multiple_asset_currencies")
    if len(fiats) != 1:
        return _review(rows, "multiple_fiat_currencies")
    asset, fiat = next(iter(assets)), next(iter(fiats))
    asset_net, cash_net = nets[asset], nets[fiat]
    if asset_net == 0 or cash_net == 0:
        return _review(rows, "zero_group_net")
    if not ((asset_net > 0 and cash_net < 0) or (asset_net < 0 and cash_net > 0)):
        return _review(rows, "contradictory_trade_direction")
    external = _external(rows, order_id, asset)
    if external is None:
        return _review(rows, "conflicting_external_id")
    anchor = min(fills, key=lambda row: (row.row.row_number, row.row.row_id))
    dates = [row.date for row in fills if row.date] or [row.date for row in rows if row.date]
    assert dates and anchor.date
    quantity, total = _decimal(asset_net), _decimal(cash_net)
    payload = {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "investment_event",
        "date": max(dates),
        "action": "buy" if asset_net > 0 else "sell",
        "external_id": external,
        "order_id": order_id,
        "raw_action": "grouped_trade",
        "asset": {"symbol": asset, "isin": None, "name": None, "asset_type_hint": "crypto"},
        "quantity": quantity,
        "price": {
            "amount": format((Decimal(total) / Decimal(quantity)).normalize(), "f"),
            "currency": fiat,
        },
        "total": {"amount": total, "currency": fiat},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "asset_direction": None,
    }
    result = [
        AnycoinRowOutcome(
            anchor.row.row_id,
            ImportRowStatus.pending,
            payload,
            _key(account_id, {"order_id": order_id}),
            None,
        )
    ]
    result.extend(
        _marker(row, "group_member", order_id, anchor.row.row_id)
        for row in rows
        if row.row.row_id != anchor.row.row_id
    )
    return result
