"""Pure canonical investment posting plans built from classified import rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from pydantic import ValidationError

from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import (
    AssetType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.imports.classification import (
    InvestmentAction,
    InvestmentEventPostingIntent,
    InvestmentMoneyPostingIntent,
    PostingIntentTarget,
    classify_import_row,
)
from app.modules.imports.posting_common import (
    DEDUPLICATION_METADATA_KEY,
    POSTING_INTENT_METADATA_KEY,
    UNIQUE_DEDUPLICATION_MARKER,
    ImportPostStateError,
    bounded_optional_text,
    copied_canonical_payload,
    exact_naive_timestamp,
    exact_numeric,
)

_ASSET_ACTIONS: Final = frozenset(
    {
        InvestmentAction.buy,
        InvestmentAction.sell,
        InvestmentAction.dividend,
        InvestmentAction.asset_transfer,
        InvestmentAction.staking_reward,
        InvestmentAction.airdrop,
    }
)
_PROVIDERS: Final = MappingProxyType(
    {
        ImportSource.trading212: PriceSource.broker,
        ImportSource.anycoin: PriceSource.exchange,
    }
)
_ASSET_TYPES: Final = MappingProxyType(
    {
        "stock": AssetType.stock,
        "stocks": AssetType.stock,
        "equity": AssetType.stock,
        "equities": AssetType.stock,
        "share": AssetType.stock,
        "shares": AssetType.stock,
        "etf": AssetType.etf,
        "exchange traded fund": AssetType.etf,
        "crypto": AssetType.crypto,
        "cryptocurrency": AssetType.crypto,
        "cryptoasset": AssetType.crypto,
        "token": AssetType.crypto,
        "commodity": AssetType.commodity,
        "bond": AssetType.bond,
        "cash": AssetType.cash,
        "other": AssetType.other,
        "unknown": AssetType.other,
    }
)


@dataclass(frozen=True, slots=True)
class InvestmentAssetResolutionPlan:
    symbol: str
    isin: str | None
    name: str | None
    asset_type: AssetType
    provider: PriceSource
    provider_symbol: str
    exchange: str
    listing_currency_hint: str | None
    asset_currency_hint: str | None


@dataclass(frozen=True, slots=True)
class InvestmentMovementPlan:
    kind: InvestmentMovementKind
    direction: MovementDirection
    quantity: Decimal
    currency: str
    requires_asset: bool
    price_per_unit: Decimal | None
    value_amount: Decimal | None
    value_currency: str | None
    source_symbol: str | None
    source_asset_type: AssetType | None
    note: str | None


@dataclass(frozen=True, slots=True)
class InvestmentEventPostingPlan:
    account_id: str
    import_batch_id: str
    source_row_id: str
    event_type: InvestmentEventType
    date: datetime
    source: ImportSource
    external_id: str | None
    order_id: str | None
    description: str | None
    realized_pnl: Decimal | None
    realized_pnl_currency: str | None
    asset_resolution: InvestmentAssetResolutionPlan | None
    movements: tuple[InvestmentMovementPlan, ...]


def _nonblank_upper(value: object) -> str:
    bounded = bounded_optional_text(value)
    if bounded is None or not bounded.strip():
        raise ImportPostStateError()
    return bounded.strip().upper()


def _asset_type(intent: InvestmentEventPostingIntent) -> AssetType:
    raw_hint = intent.asset.asset_type_hint
    normalized_hint = (
        " ".join(raw_hint.strip().casefold().split()) if isinstance(raw_hint, str) else ""
    )
    mapped = _ASSET_TYPES.get(normalized_hint, AssetType.other)
    if intent.source is ImportSource.anycoin:
        if normalized_hint and mapped is not AssetType.crypto:
            raise ImportPostStateError()
        return AssetType.crypto
    return mapped


def _asset_resolution(
    intent: InvestmentEventPostingIntent,
) -> InvestmentAssetResolutionPlan | None:
    if intent.action not in _ASSET_ACTIONS:
        return None
    symbol = _nonblank_upper(intent.asset.symbol)
    isin = None if intent.asset.isin is None else _nonblank_upper(intent.asset.isin)
    name = bounded_optional_text(intent.asset.name)
    asset_type = _asset_type(intent)
    if intent.action in {InvestmentAction.buy, InvestmentAction.sell}:
        if intent.total is None:
            raise ImportPostStateError()
        listing_currency = (
            intent.price.currency if intent.price is not None else intent.total.currency
        )
    elif intent.action is InvestmentAction.dividend:
        listing_currency = None
    elif asset_type is AssetType.crypto:
        listing_currency = symbol
    else:
        listing_currency = intent.price.currency if intent.price is not None else None
    asset_currency = symbol if asset_type is AssetType.crypto else listing_currency
    provider = _PROVIDERS.get(intent.source)
    if provider is None:
        raise ImportPostStateError()
    return InvestmentAssetResolutionPlan(
        symbol=symbol,
        isin=isin,
        name=name,
        asset_type=asset_type,
        provider=provider,
        provider_symbol=symbol,
        exchange=intent.source.value,
        listing_currency_hint=listing_currency,
        asset_currency_hint=asset_currency,
    )


def _movement(
    *,
    kind: InvestmentMovementKind,
    direction: MovementDirection,
    quantity: Decimal,
    currency: str,
    requires_asset: bool,
    price_per_unit: Decimal | None = None,
    value_amount: Decimal | None = None,
    value_currency: str | None = None,
    asset: InvestmentAssetResolutionPlan | None = None,
    note: str | None,
) -> InvestmentMovementPlan:
    exact_quantity = exact_numeric(quantity, QUANTITY)
    if exact_quantity <= 0:
        raise ImportPostStateError()
    exact_price = None if price_per_unit is None else exact_numeric(price_per_unit, QUANTITY)
    exact_value = None if value_amount is None else exact_numeric(value_amount, QUANTITY)
    if (exact_price is not None and exact_price <= 0) or (
        exact_value is not None and exact_value <= 0
    ):
        raise ImportPostStateError()
    if requires_asset and asset is None:
        raise ImportPostStateError()
    return InvestmentMovementPlan(
        kind=kind,
        direction=direction,
        quantity=exact_quantity,
        currency=_nonblank_upper(currency),
        requires_asset=requires_asset,
        price_per_unit=exact_price,
        value_amount=exact_value,
        value_currency=(None if value_currency is None else _nonblank_upper(value_currency)),
        source_symbol=asset.symbol if requires_asset and asset is not None else None,
        source_asset_type=asset.asset_type if requires_asset and asset is not None else None,
        note=note,
    )


def _cash_movement(
    money: InvestmentMoneyPostingIntent,
    direction: MovementDirection,
    *,
    note: str | None,
    asset: InvestmentAssetResolutionPlan | None = None,
) -> InvestmentMovementPlan:
    return _movement(
        kind=InvestmentMovementKind.cash,
        direction=direction,
        quantity=money.amount,
        currency=money.currency,
        requires_asset=asset is not None,
        value_amount=money.amount,
        value_currency=money.currency,
        asset=asset,
        note=note,
    )


def _fee_movement(
    fee: InvestmentMoneyPostingIntent,
    *,
    note: str | None,
) -> InvestmentMovementPlan:
    return _movement(
        kind=InvestmentMovementKind.fee,
        direction=MovementDirection.outgoing,
        quantity=fee.amount,
        currency=fee.currency,
        requires_asset=False,
        value_amount=fee.amount,
        value_currency=fee.currency,
        note=note,
    )


def _asset_movement(
    intent: InvestmentEventPostingIntent,
    asset: InvestmentAssetResolutionPlan,
    direction: MovementDirection,
    *,
    note: str | None,
) -> InvestmentMovementPlan:
    if intent.quantity is None:
        raise ImportPostStateError()
    return _movement(
        kind=InvestmentMovementKind.asset,
        direction=direction,
        quantity=intent.quantity,
        currency=asset.symbol,
        requires_asset=True,
        price_per_unit=intent.price.amount if intent.price is not None else None,
        value_amount=intent.total.amount if intent.total is not None else None,
        value_currency=intent.total.currency if intent.total is not None else None,
        asset=asset,
        note=note,
    )


def _movements(
    intent: InvestmentEventPostingIntent,
    asset: InvestmentAssetResolutionPlan | None,
    *,
    note: str | None,
) -> tuple[InvestmentMovementPlan, ...]:
    result: list[InvestmentMovementPlan] = []
    if intent.action in {InvestmentAction.buy, InvestmentAction.sell}:
        if asset is None or intent.total is None:
            raise ImportPostStateError()
        asset_direction = (
            MovementDirection.incoming
            if intent.action is InvestmentAction.buy
            else MovementDirection.outgoing
        )
        cash_direction = (
            MovementDirection.outgoing
            if intent.action is InvestmentAction.buy
            else MovementDirection.incoming
        )
        result.extend(
            (
                _asset_movement(intent, asset, asset_direction, note=note),
                _cash_movement(intent.total, cash_direction, note=note),
            )
        )
    elif intent.action is InvestmentAction.dividend:
        if asset is None or intent.total is None:
            raise ImportPostStateError()
        result.append(
            _cash_movement(intent.total, MovementDirection.incoming, note=note, asset=asset)
        )
    elif intent.action in {InvestmentAction.interest, InvestmentAction.cash_deposit}:
        if intent.total is None:
            raise ImportPostStateError()
        result.append(_cash_movement(intent.total, MovementDirection.incoming, note=note))
    elif intent.action is InvestmentAction.cash_withdrawal:
        if intent.total is None:
            raise ImportPostStateError()
        result.append(_cash_movement(intent.total, MovementDirection.outgoing, note=note))
    elif intent.action is InvestmentAction.currency_conversion:
        if intent.conversion is None:
            raise ImportPostStateError()
        result.extend(
            (
                _cash_movement(intent.conversion.from_, MovementDirection.outgoing, note=note),
                _cash_movement(intent.conversion.to, MovementDirection.incoming, note=note),
            )
        )
    elif intent.action is InvestmentAction.asset_transfer:
        if asset is None:
            raise ImportPostStateError()
        direction = (
            MovementDirection.incoming
            if intent.asset_direction == "in"
            else MovementDirection.outgoing
        )
        result.append(_asset_movement(intent, asset, direction, note=note))
    elif intent.action is InvestmentAction.fee:
        if intent.total is None:
            raise ImportPostStateError()
        result.append(_fee_movement(intent.total, note=note))
    elif intent.action in {InvestmentAction.staking_reward, InvestmentAction.airdrop}:
        if asset is None:
            raise ImportPostStateError()
        result.append(_asset_movement(intent, asset, MovementDirection.incoming, note=note))
    else:
        raise ImportPostStateError()
    if intent.fee is not None:
        result.append(_fee_movement(intent.fee, note=note))
    if not result:
        raise ImportPostStateError()
    return tuple(result)


def _description(
    intent: InvestmentEventPostingIntent,
    asset: InvestmentAssetResolutionPlan | None,
) -> str | None:
    candidates = (
        intent.asset.name,
        asset.symbol if asset is not None else intent.asset.symbol,
        intent.raw_action,
        intent.note,
    )
    for candidate in candidates:
        value = bounded_optional_text(candidate)
        if value is not None and value.strip():
            return value
    return None


def build_investment_posting_plan(
    *,
    account_id: str,
    batch: ImportBatchModel,
    row: ImportRowModel,
) -> InvestmentEventPostingPlan:
    if (
        batch.account_id != account_id
        or batch.status is not ImportStatus.processing
        or row.import_batch_id != batch.id
        or row.status not in {ImportRowStatus.pending, ImportRowStatus.imported}
        or not isinstance(row.normalized_data, dict)
        or row.normalized_data.get(DEDUPLICATION_METADATA_KEY) != UNIQUE_DEDUPLICATION_MARKER
        or not isinstance(row.deduplication_key, str)
        or not row.deduplication_key
        or row.validation_errors is not None
        or row.error_message is not None
    ):
        raise ImportPostStateError()
    if row.status is ImportRowStatus.pending and (
        row.created_transaction_id is not None or row.created_investment_event_id is not None
    ):
        raise ImportPostStateError()
    if row.status is ImportRowStatus.imported and (
        row.created_transaction_id is not None
        or not isinstance(row.created_investment_event_id, str)
        or not row.created_investment_event_id
    ):
        raise ImportPostStateError()

    stored = row.normalized_data.get(POSTING_INTENT_METADATA_KEY)
    if not isinstance(stored, dict):
        raise ImportPostStateError()
    canonical = copied_canonical_payload(row.normalized_data)
    fresh = classify_import_row(
        source=batch.source,
        normalized_data=canonical,
    ).model_dump(mode="json")
    if (
        fresh != stored
        or fresh.get("schema_version") != 1
        or fresh.get("target") != PostingIntentTarget.investment_event.value
    ):
        raise ImportPostStateError()
    try:
        intent = InvestmentEventPostingIntent.model_validate(stored)
    except ValidationError as exc:
        raise ImportPostStateError() from exc

    asset = _asset_resolution(intent)
    note = bounded_optional_text(intent.note)
    realized_pnl = (
        None if intent.realized_pnl is None else exact_numeric(intent.realized_pnl.amount, QUANTITY)
    )
    return InvestmentEventPostingPlan(
        account_id=batch.account_id,
        import_batch_id=batch.id,
        source_row_id=row.id,
        event_type=intent.investment_event_type,
        date=exact_naive_timestamp(intent.date, TIMESTAMP),
        source=intent.source,
        external_id=bounded_optional_text(intent.external_id),
        order_id=bounded_optional_text(intent.order_id),
        description=_description(intent, asset),
        realized_pnl=realized_pnl,
        realized_pnl_currency=(
            intent.realized_pnl.currency if intent.realized_pnl is not None else None
        ),
        asset_resolution=asset,
        movements=_movements(intent, asset, note=note),
    )
