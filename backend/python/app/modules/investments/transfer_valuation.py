"""Read-only resolution of append-only investment transfer valuation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from app.db.models.common import QUANTITY, RATE, TIMESTAMP
from app.db.models.enums import (
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    PriceSource,
)
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.shared.canonical_arithmetic import CanonicalArithmeticError, canonical_rounded


class TransferValuationStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Investment transfer valuation evidence is invalid.")


@dataclass(frozen=True, slots=True)
class ResolvedTransferValuation:
    evidence_id: str
    price_per_unit: Decimal
    value_amount: Decimal
    value_currency: str


def _fail() -> TransferValuationStateError:
    return TransferValuationStateError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or not result.isascii() or not result.isalpha() or result != result.upper():
        raise _fail()
    return result


def _decimal(value: object, *, scale: int, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    try:
        exact = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if exact != value or (positive and value <= 0):
        raise _fail()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def index_latest_transfer_valuations(
    rows: tuple[InvestmentMovementValuationEvidenceModel, ...]
    | list[InvestmentMovementValuationEvidenceModel],
) -> dict[str, InvestmentMovementValuationEvidenceModel]:
    """Return one latest evidence row per movement after proving contiguous revisions."""

    grouped: dict[str, list[InvestmentMovementValuationEvidenceModel]] = {}
    ids: set[str] = set()
    for row in rows:
        evidence_id = _text(row.id)
        movement_id = _text(row.movement_id)
        if evidence_id in ids:
            raise _fail()
        ids.add(evidence_id)
        grouped.setdefault(movement_id, []).append(row)
    result: dict[str, InvestmentMovementValuationEvidenceModel] = {}
    for movement_id, values in grouped.items():
        ordered = sorted(values, key=lambda item: item.revision)
        if [item.revision for item in ordered] != list(range(1, len(ordered) + 1)):
            raise _fail()
        result[movement_id] = ordered[-1]
    return result


def transfer_valuation_fingerprint(
    *,
    movement: InvestmentMovementModel,
    effective_at: datetime,
    canonical_revision: int,
    price_snapshot_id: str,
    exchange_rate_id: str,
    calculation_version: int,
    selection_interval: str,
) -> str:
    payload = "\0".join(
        (
            _text(movement.id),
            _timestamp(effective_at).isoformat(timespec="milliseconds"),
            format(_decimal(movement.quantity, scale=QUANTITY.scale or 10, positive=True), "f"),
            movement.direction.value,
            str(canonical_revision),
            _text(price_snapshot_id),
            _text(exchange_rate_id),
            str(calculation_version),
            _text(selection_interval),
        )
    )
    return sha256(payload.encode()).hexdigest()


def resolve_transfer_valuation(
    *,
    event: InvestmentEventModel,
    movement: InvestmentMovementModel,
    evidence: InvestmentMovementValuationEvidenceModel | None,
    canonical_revision: int | None = None,
) -> ResolvedTransferValuation | None:
    """Validate and expose an evidence overlay without mutating the canonical movement."""

    canonical_values = (
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
    )
    if evidence is None:
        if (
            event.source is ImportSource.anycoin
            and event.type is InvestmentEventType.asset_transfer
            and movement.kind is InvestmentMovementKind.asset
            and movement.source_symbol == "BTC"
            and movement.currency == "BTC"
            and movement.source_asset_type is AssetType.crypto
            and movement.asset_id is not None
            and movement.listing_id is not None
            and all(value is None for value in canonical_values)
        ):
            raise _fail()
        return None
    if (
        event.source is not ImportSource.anycoin
        or event.type is not InvestmentEventType.asset_transfer
        or movement.kind is not InvestmentMovementKind.asset
        or movement.source_symbol != "BTC"
        or movement.currency != "BTC"
        or movement.source_asset_type is not AssetType.crypto
        or movement.asset_id is None
        or movement.listing_id is None
        or any(value is not None for value in canonical_values)
        or evidence.account_id != event.account_id
        or evidence.account_id != movement.account_id
        or evidence.movement_id != movement.id
        or evidence.effective_at != event.date
        or evidence.canonical_revision != canonical_revision
        or not isinstance(evidence.revision, int)
        or isinstance(evidence.revision, bool)
        or evidence.revision <= 0
        or not isinstance(evidence.canonical_revision, int)
        or isinstance(evidence.canonical_revision, bool)
        or evidence.canonical_revision <= 0
        or not isinstance(evidence.calculation_version, int)
        or isinstance(evidence.calculation_version, bool)
        or evidence.calculation_version <= 0
        or evidence.selection_interval not in {"30min", "1day"}
    ):
        raise _fail()
    _text(evidence.input_fingerprint)
    _text(evidence.price_snapshot_id)
    price_currency = _currency(evidence.price_currency)
    value_currency = _currency(evidence.value_currency)
    price_timestamp = _timestamp(evidence.price_timestamp)
    if (
        price_currency != "USD"
        or value_currency != "CZK"
        or evidence.price_source is not PriceSource.yahoo_finance
        or price_timestamp > event.date
        or price_timestamp.date() != event.date.date()
        or event.date - price_timestamp > DEFAULT_MARKET_EVIDENCE_POLICY.maximum_price_age
    ):
        raise _fail()
    price = _decimal(evidence.price_amount, scale=QUANTITY.scale or 10, positive=True)
    stored_unit = _decimal(evidence.price_per_unit, scale=QUANTITY.scale or 10, positive=True)
    stored_value = _decimal(evidence.value_amount, scale=QUANTITY.scale or 10, positive=True)
    quantity = _decimal(movement.quantity, scale=QUANTITY.scale or 10, positive=True)

    if any(
        value is None
        for value in (
            evidence.exchange_rate_id,
            evidence.fx_rate,
            evidence.fx_from_currency,
            evidence.fx_to_currency,
            evidence.fx_source,
            evidence.fx_timestamp,
        )
    ):
        raise _fail()
    exchange_rate_id = _text(evidence.exchange_rate_id)
    fx_timestamp = _timestamp(evidence.fx_timestamp)
    if (
        _currency(evidence.fx_from_currency) != "USD"
        or _currency(evidence.fx_to_currency) != "CZK"
        or evidence.fx_source is not ExchangeRateSource.yahoo_finance
        or fx_timestamp > event.date
        or event.date - fx_timestamp > DEFAULT_MARKET_EVIDENCE_POLICY.maximum_fx_age
    ):
        raise _fail()
    rate = _decimal(evidence.fx_rate, scale=RATE.scale or 8, positive=True)
    if evidence.input_fingerprint != transfer_valuation_fingerprint(
        movement=movement,
        effective_at=event.date,
        canonical_revision=evidence.canonical_revision,
        price_snapshot_id=evidence.price_snapshot_id,
        exchange_rate_id=exchange_rate_id,
        calculation_version=evidence.calculation_version,
        selection_interval=evidence.selection_interval,
    ):
        raise _fail()
    try:
        expected_unit = canonical_rounded(price * rate, QUANTITY)
        expected_value = canonical_rounded(quantity * expected_unit, QUANTITY)
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    if stored_unit != expected_unit or stored_value != expected_value:
        raise _fail()
    return ResolvedTransferValuation(
        evidence_id=_text(evidence.id),
        price_per_unit=stored_unit,
        value_amount=stored_value,
        value_currency=value_currency,
    )


def validate_transfer_valuation_citations(
    *,
    evidence: InvestmentMovementValuationEvidenceModel,
    movement: InvestmentMovementModel,
    price: PriceSnapshotModel | None,
    exchange_rate: ExchangeRateModel | None,
) -> None:
    """Prove that every denormalized monetary field matches its immutable citation."""

    exact_price_identity = price is not None and (
        price.listing_id == movement.listing_id
        or (
            movement.source_symbol == "BTC"
            and movement.currency == "BTC"
            and movement.source_asset_type is AssetType.crypto
            and price.source is PriceSource.yahoo_finance
            and price.currency == "USD"
            and getattr(price, "provider_symbol", None) == "BTC-USD"
        )
    )
    if (
        price is None
        or price.id != evidence.price_snapshot_id
        or price.price != evidence.price_amount
        or price.currency != evidence.price_currency
        or price.source is not evidence.price_source
        or price.timestamp != evidence.price_timestamp
        or price.asset_id != movement.asset_id
        or not exact_price_identity
    ):
        raise _fail()
    if evidence.exchange_rate_id is None:
        if exchange_rate is not None:
            raise _fail()
        return
    if (
        exchange_rate is None
        or exchange_rate.id != evidence.exchange_rate_id
        or exchange_rate.rate != evidence.fx_rate
        or exchange_rate.from_currency != evidence.fx_from_currency
        or exchange_rate.to_currency != evidence.fx_to_currency
        or exchange_rate.source is not evidence.fx_source
        or exchange_rate.date != evidence.fx_timestamp
    ):
        raise _fail()


__all__ = [
    "ResolvedTransferValuation",
    "TransferValuationStateError",
    "index_latest_transfer_valuations",
    "resolve_transfer_valuation",
    "transfer_valuation_fingerprint",
    "validate_transfer_valuation_citations",
]
