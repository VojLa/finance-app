"""Canonical bounded checkpoint encoding for pure replay state."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn, cast

from app.db.models.common import MONEY, QUANTITY
from app.db.models.enums import AccountType, AssetType
from app.modules.holdings.persistence_projection import ExpectedPersistedHoldingPlan
from app.modules.portfolio_history_rebuild.models import (
    AccountReplayState,
    CurrencyAmount,
    LiabilityReplayState,
    PortfolioHistoryReplayError,
    ReplayCursor,
    ReplayMetrics,
    ReplayRootKind,
)
from app.modules.portfolio_history_rebuild.replay import advance_account_replay

CHECKPOINT_SCHEMA_VERSION = 1
MAX_CHECKPOINT_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class ReplayCheckpointDocument:
    payload: bytes
    sha256: str


def _fail(message: str) -> NoReturn:
    raise PortfolioHistoryReplayError(message)


def _keys(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        _fail("Checkpoint object fields do not match its schema.")
    return cast(dict[str, Any], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        _fail("Checkpoint string field is invalid.")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is not None or value.microsecond % 1000:
        _fail("Checkpoint timestamps must be naive UTC milliseconds.")
    return value.isoformat(timespec="milliseconds")


def _parse_datetime(value: object) -> datetime:
    text = _string(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PortfolioHistoryReplayError("Checkpoint timestamp is invalid.") from exc
    if parsed.tzinfo is not None or _datetime_text(parsed) != text:
        _fail("Checkpoint timestamp is not canonical UTC milliseconds.")
    return parsed


def _decimal_text(value: Decimal, *, scale: int, precision: int) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        _fail("Checkpoint decimal is invalid.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        scaled = value.quantize(quantum)
    except InvalidOperation as exc:
        raise PortfolioHistoryReplayError("Checkpoint decimal is invalid.") from exc
    if scaled != value or abs(value) >= Decimal(10) ** (precision - scale):
        _fail("Checkpoint decimal violates its canonical numeric contract.")
    return format(value, f".{scale}f")


def _parse_decimal(value: object, *, scale: int, precision: int) -> Decimal:
    text = _string(value)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise PortfolioHistoryReplayError("Checkpoint decimal is invalid.") from exc
    if _decimal_text(parsed, scale=scale, precision=precision) != text:
        _fail("Checkpoint decimal is not in fixed-scale canonical form.")
    return parsed


def _money_text(value: Decimal) -> str:
    assert MONEY.scale is not None and MONEY.precision is not None
    return _decimal_text(value, scale=MONEY.scale, precision=MONEY.precision)


def _quantity_text(value: Decimal) -> str:
    assert QUANTITY.scale is not None and QUANTITY.precision is not None
    return _decimal_text(value, scale=QUANTITY.scale, precision=QUANTITY.precision)


def _parse_money(value: object) -> Decimal:
    assert MONEY.scale is not None and MONEY.precision is not None
    return _parse_decimal(value, scale=MONEY.scale, precision=MONEY.precision)


def _parse_quantity(value: object) -> Decimal:
    assert QUANTITY.scale is not None and QUANTITY.precision is not None
    return _parse_decimal(value, scale=QUANTITY.scale, precision=QUANTITY.precision)


def _amounts_to_json(values: tuple[CurrencyAmount, ...]) -> list[dict[str, str]]:
    currencies = tuple(value.currency for value in values)
    if currencies != tuple(sorted(set(currencies))):
        _fail("Checkpoint currency totals must be uniquely and canonically sorted.")
    return [{"amount": _money_text(value.amount), "currency": value.currency} for value in values]


def _amounts_from_json(value: object) -> tuple[CurrencyAmount, ...]:
    if not isinstance(value, list):
        _fail("Checkpoint currency totals must be an array.")
    result = tuple(
        CurrencyAmount(
            currency=_string(_keys(item, {"amount", "currency"})["currency"]),
            amount=_parse_money(_keys(item, {"amount", "currency"})["amount"]),
        )
        for item in value
    )
    if tuple(item.currency for item in result) != tuple(sorted(item.currency for item in result)):
        _fail("Checkpoint currency totals are not canonically sorted.")
    if len({item.currency for item in result}) != len(result):
        _fail("Checkpoint currency totals contain duplicate currencies.")
    return result


def _holding_to_json(holding: ExpectedPersistedHoldingPlan) -> dict[str, object]:
    if any(
        value is not None
        for value in (
            holding.current_price,
            holding.current_value,
            holding.unrealized_pnl,
            holding.realized_pnl,
        )
    ):
        _fail("Replay checkpoints cannot contain valuation output.")
    return {
        "accountId": holding.account_id,
        "assetId": holding.asset_id,
        "assetType": holding.asset_type.value,
        "avgBuyPrice": None
        if holding.avg_buy_price is None
        else _quantity_text(holding.avg_buy_price),
        "costBasisByCurrency": (
            None
            if holding.cost_basis_by_currency is None
            else [
                {"amount": _quantity_text(amount), "currency": currency}
                for currency, amount in holding.cost_basis_by_currency
            ]
        ),
        "currency": holding.currency,
        "listingId": holding.listing_id,
        "name": holding.name,
        "quantity": _quantity_text(holding.quantity),
        "symbol": holding.symbol,
    }


def _holding_from_json(value: object) -> ExpectedPersistedHoldingPlan:
    item = _keys(
        value,
        {
            "accountId",
            "assetId",
            "assetType",
            "avgBuyPrice",
            "costBasisByCurrency",
            "currency",
            "listingId",
            "name",
            "quantity",
            "symbol",
        },
    )
    raw_cost = item["costBasisByCurrency"]
    if raw_cost is None:
        cost_basis = None
    else:
        if not isinstance(raw_cost, list):
            _fail("Checkpoint cost basis must be an array or null.")
        cost_basis = tuple(
            (
                _string(_keys(entry, {"amount", "currency"})["currency"]),
                _parse_quantity(_keys(entry, {"amount", "currency"})["amount"]),
            )
            for entry in raw_cost
        )
        if tuple(currency for currency, _ in cost_basis) != tuple(
            sorted(currency for currency, _ in cost_basis)
        ):
            _fail("Checkpoint cost basis is not canonically sorted.")
    try:
        asset_type = AssetType(_string(item["assetType"]))
    except ValueError as exc:
        raise PortfolioHistoryReplayError("Checkpoint asset type is invalid.") from exc
    return ExpectedPersistedHoldingPlan(
        account_id=_string(item["accountId"]),
        asset_id=_string(item["assetId"]),
        listing_id=_string(item["listingId"]),
        symbol=_string(item["symbol"]),
        name=_optional_string(item["name"]),
        asset_type=asset_type,
        quantity=_parse_quantity(item["quantity"]),
        avg_buy_price=None if item["avgBuyPrice"] is None else _parse_quantity(item["avgBuyPrice"]),
        currency=_string(item["currency"]),
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        cost_basis_by_currency=cost_basis,
    )


def _state_to_json(state: AccountReplayState) -> dict[str, object]:
    metrics = state.metrics
    liability = state.liability
    return {
        "accountCurrency": state.account_currency,
        "accountId": state.account_id,
        "accountType": state.account_type.value,
        "active": state.active,
        "cashByCurrency": _amounts_to_json(state.cash_by_currency),
        "cursor": (
            None
            if state.cursor is None
            else {
                "entityId": state.cursor.entity_id,
                "kind": state.cursor.kind.value,
                "timestamp": _datetime_text(state.cursor.timestamp),
            }
        ),
        "holdings": [_holding_to_json(holding) for holding in state.holdings],
        "liability": (
            None
            if liability is None
            else {
                "accruedInterest": _money_text(liability.accrued_interest),
                "balanceId": liability.balance_id,
                "currency": liability.currency,
                "effectiveAt": _datetime_text(liability.effective_at),
                "feesOutstanding": _money_text(liability.fees_outstanding),
                "outstandingPrincipal": _money_text(liability.outstanding_principal),
                "totalOutstanding": _money_text(liability.total_outstanding),
            }
        ),
        "metrics": {
            "fees": _amounts_to_json(metrics.fees),
            "hasAssetTransfer": metrics.has_asset_transfer,
            "netDeposits": _amounts_to_json(metrics.net_deposits),
            "realizedPnl": _amounts_to_json(metrics.realized_pnl),
            "taxes": _amounts_to_json(metrics.taxes),
        },
        "through": None if state.through is None else _datetime_text(state.through),
    }


def _state_from_json(value: object) -> AccountReplayState:
    item = _keys(
        value,
        {
            "accountCurrency",
            "accountId",
            "accountType",
            "active",
            "cashByCurrency",
            "cursor",
            "holdings",
            "liability",
            "metrics",
            "through",
        },
    )
    try:
        account_type = AccountType(_string(item["accountType"]))
    except ValueError as exc:
        raise PortfolioHistoryReplayError("Checkpoint account type is invalid.") from exc
    if not isinstance(item["active"], bool):
        _fail("Checkpoint active flag is invalid.")
    raw_cursor = item["cursor"]
    if raw_cursor is None:
        cursor = None
    else:
        cursor_item = _keys(raw_cursor, {"entityId", "kind", "timestamp"})
        try:
            kind = ReplayRootKind(_string(cursor_item["kind"]))
        except ValueError as exc:
            raise PortfolioHistoryReplayError("Checkpoint cursor kind is invalid.") from exc
        cursor = ReplayCursor(
            timestamp=_parse_datetime(cursor_item["timestamp"]),
            kind=kind,
            entity_id=_string(cursor_item["entityId"]),
        )
    raw_holdings = item["holdings"]
    if not isinstance(raw_holdings, list):
        _fail("Checkpoint holdings must be an array.")
    holdings = tuple(_holding_from_json(holding) for holding in raw_holdings)
    if tuple(holding.listing_id for holding in holdings) != tuple(
        sorted(holding.listing_id for holding in holdings)
    ):
        _fail("Checkpoint holdings are not canonically sorted.")
    raw_metrics = _keys(
        item["metrics"], {"fees", "hasAssetTransfer", "netDeposits", "realizedPnl", "taxes"}
    )
    if not isinstance(raw_metrics["hasAssetTransfer"], bool):
        _fail("Checkpoint transfer flag is invalid.")
    raw_liability = item["liability"]
    if raw_liability is None:
        liability = None
    else:
        liability_item = _keys(
            raw_liability,
            {
                "accruedInterest",
                "balanceId",
                "currency",
                "effectiveAt",
                "feesOutstanding",
                "outstandingPrincipal",
                "totalOutstanding",
            },
        )
        liability = LiabilityReplayState(
            balance_id=_string(liability_item["balanceId"]),
            effective_at=_parse_datetime(liability_item["effectiveAt"]),
            currency=_string(liability_item["currency"]),
            outstanding_principal=_parse_money(liability_item["outstandingPrincipal"]),
            accrued_interest=_parse_money(liability_item["accruedInterest"]),
            fees_outstanding=_parse_money(liability_item["feesOutstanding"]),
            total_outstanding=_parse_money(liability_item["totalOutstanding"]),
        )
    return AccountReplayState(
        account_id=_string(item["accountId"]),
        account_type=account_type,
        account_currency=_string(item["accountCurrency"]),
        active=item["active"],
        through=None if item["through"] is None else _parse_datetime(item["through"]),
        cursor=cursor,
        cash_by_currency=_amounts_from_json(item["cashByCurrency"]),
        holdings=holdings,
        metrics=ReplayMetrics(
            net_deposits=_amounts_from_json(raw_metrics["netDeposits"]),
            realized_pnl=_amounts_from_json(raw_metrics["realizedPnl"]),
            fees=_amounts_from_json(raw_metrics["fees"]),
            taxes=_amounts_from_json(raw_metrics["taxes"]),
            has_asset_transfer=raw_metrics["hasAssetTransfer"],
        ),
        liability=liability,
    )


def encode_replay_checkpoint(state: AccountReplayState) -> ReplayCheckpointDocument:
    """Encode one state as canonical sorted JSON and hash its exact bytes."""

    advance_account_replay(state, ())
    payload = json.dumps(
        {"schemaVersion": CHECKPOINT_SCHEMA_VERSION, "state": _state_to_json(state)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > MAX_CHECKPOINT_BYTES:
        _fail("Replay checkpoint exceeds the 1 MiB limit.")
    return ReplayCheckpointDocument(payload=payload, sha256=hashlib.sha256(payload).hexdigest())


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("Checkpoint JSON contains duplicate keys.")
        result[key] = value
    return result


def decode_replay_checkpoint(payload: bytes, expected_sha256: str) -> AccountReplayState:
    """Verify hash, size, schema and canonical bytes before restoring a state."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CHECKPOINT_BYTES:
        _fail("Replay checkpoint payload is invalid or too large.")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or not hmac.compare_digest(actual_hash, expected_sha256.lower())
    ):
        _fail("Replay checkpoint hash mismatch.")
    try:
        parsed = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PortfolioHistoryReplayError("Replay checkpoint JSON is invalid.") from exc
    document = _keys(parsed, {"schemaVersion", "state"})
    if document["schemaVersion"] != CHECKPOINT_SCHEMA_VERSION:
        _fail("Replay checkpoint schema version is unsupported.")
    state = _state_from_json(document["state"])
    canonical = encode_replay_checkpoint(state)
    if canonical.payload != payload:
        _fail("Replay checkpoint JSON is not canonical.")
    return state
