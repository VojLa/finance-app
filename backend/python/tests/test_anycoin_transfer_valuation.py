from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from app.db.models.enums import (
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.investments.anycoin_transfer_valuation_service import (
    require_same_day_selections,
)
from app.modules.investments.transfer_valuation import (
    TransferValuationStateError,
    index_latest_transfer_valuations,
    resolve_transfer_valuation,
    transfer_valuation_fingerprint,
    validate_transfer_valuation_citations,
)
from app.modules.market_data.history.models import HistoricalMarketEvidenceStateError

EVENT_AT = datetime(2024, 1, 2, 12)


def _event() -> InvestmentEventModel:
    return cast(
        InvestmentEventModel,
        SimpleNamespace(
            id="event",
            account_id="account",
            source=ImportSource.anycoin,
            type=InvestmentEventType.asset_transfer,
            date=EVENT_AT,
        ),
    )


def _movement() -> InvestmentMovementModel:
    return cast(
        InvestmentMovementModel,
        SimpleNamespace(
            id="movement",
            event_id="event",
            account_id="account",
            kind=InvestmentMovementKind.asset,
            currency="BTC",
            source_symbol="BTC",
            source_asset_type=AssetType.crypto,
            asset_id="asset-btc",
            listing_id="listing-btc",
            quantity=Decimal("0.0200000000"),
            direction=MovementDirection.incoming,
            price_per_unit=None,
            value_amount=None,
            value_currency=None,
        ),
    )


def _evidence(**changes: object) -> InvestmentMovementValuationEvidenceModel:
    values: dict[str, object] = {
        "id": "evidence",
        "account_id": "account",
        "movement_id": "movement",
        "revision": 1,
        "canonical_revision": 1,
        "effective_at": EVENT_AT,
        "calculation_version": 1,
        "selection_interval": "30min",
        "price_snapshot_id": "price",
        "exchange_rate_id": "fx",
        "price_amount": Decimal("50000.0000000000"),
        "price_currency": "USD",
        "price_source": PriceSource.yahoo_finance,
        "price_timestamp": datetime(2024, 1, 2),
        "fx_rate": Decimal("23.00000000"),
        "fx_from_currency": "USD",
        "fx_to_currency": "CZK",
        "fx_source": ExchangeRateSource.yahoo_finance,
        "fx_timestamp": datetime(2024, 1, 2),
        "price_per_unit": Decimal("1150000.0000000000"),
        "value_amount": Decimal("23000.0000000000"),
        "value_currency": "CZK",
    }
    values.update(changes)
    values.setdefault(
        "input_fingerprint",
        transfer_valuation_fingerprint(
            movement=_movement(),
            effective_at=EVENT_AT,
            canonical_revision=cast(int, values["canonical_revision"]),
            price_snapshot_id=cast(str, values["price_snapshot_id"]),
            exchange_rate_id=cast(str, values["exchange_rate_id"]),
            calculation_version=cast(int, values["calculation_version"]),
            selection_interval=cast(str, values["selection_interval"]),
        ),
    )
    return cast(InvestmentMovementValuationEvidenceModel, SimpleNamespace(**values))


def test_resolves_evidence_without_mutating_canonical_movement() -> None:
    movement = _movement()

    result = resolve_transfer_valuation(
        event=_event(), movement=movement, evidence=_evidence(), canonical_revision=1
    )

    assert result is not None
    assert result.price_per_unit == Decimal("1150000.0000000000")
    assert result.value_amount == Decimal("23000.0000000000")
    assert movement.price_per_unit is None
    assert movement.value_amount is None
    assert movement.value_currency is None


def test_missing_evidence_for_exact_anycoin_transfer_fails_closed() -> None:
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=None,
            canonical_revision=1,
        )


def test_rejects_future_fx_evidence_and_accepts_recent_prior_business_day() -> None:
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(fx_timestamp=datetime(2024, 1, 3)),
            canonical_revision=1,
        )
    result = resolve_transfer_valuation(
        event=_event(),
        movement=_movement(),
        evidence=_evidence(fx_timestamp=datetime(2024, 1, 1)),
        canonical_revision=1,
    )
    assert result is not None
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(fx_timestamp=datetime(2023, 12, 25)),
            canonical_revision=1,
        )


def test_rejects_non_btc_transfer_even_with_well_formed_values() -> None:
    movement = _movement()
    movement.source_symbol = "ETH"
    movement.currency = "ETH"
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(), movement=movement, evidence=_evidence(), canonical_revision=1
        )
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(fx_from_currency="EUR"),
            canonical_revision=1,
        )


def test_latest_revision_requires_contiguous_append_only_lineage() -> None:
    latest = _evidence(id="second", revision=2, canonical_revision=7)
    indexed = index_latest_transfer_valuations([_evidence(), latest])
    assert indexed["movement"] is latest

    with pytest.raises(TransferValuationStateError):
        index_latest_transfer_valuations([_evidence(revision=2, canonical_revision=7)])


def test_rejects_unapproved_anycoin_market_sources() -> None:
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(price_source=PriceSource.manual),
            canonical_revision=1,
        )
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(fx_source=ExchangeRateSource.manual),
            canonical_revision=1,
        )


def test_copied_values_must_match_cited_market_rows() -> None:
    evidence = _evidence()
    price = cast(
        PriceSnapshotModel,
        SimpleNamespace(
            id="price",
            asset_id="asset-btc",
            listing_id="listing-btc",
            price=Decimal("50000.0000000000"),
            currency="USD",
            source=PriceSource.yahoo_finance,
            timestamp=datetime(2024, 1, 2),
        ),
    )
    rate = cast(
        ExchangeRateModel,
        SimpleNamespace(
            id="fx",
            rate=Decimal("23.00000000"),
            from_currency="USD",
            to_currency="CZK",
            source=ExchangeRateSource.yahoo_finance,
            date=datetime(2024, 1, 2),
        ),
    )
    validate_transfer_valuation_citations(
        evidence=evidence, movement=_movement(), price=price, exchange_rate=rate
    )
    rate.rate = Decimal("22.00000000")
    with pytest.raises(TransferValuationStateError):
        validate_transfer_valuation_citations(
            evidence=evidence, movement=_movement(), price=price, exchange_rate=rate
        )


def test_rejects_wrong_canonical_revision_or_fingerprint() -> None:
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(),
            canonical_revision=999,
        )
    with pytest.raises(TransferValuationStateError):
        resolve_transfer_valuation(
            event=_event(),
            movement=_movement(),
            evidence=_evidence(input_fingerprint="wrong"),
            canonical_revision=1,
        )


def test_rejects_price_citation_for_different_asset_identity() -> None:
    evidence = _evidence()
    price = cast(
        PriceSnapshotModel,
        SimpleNamespace(
            id="price",
            asset_id="asset-eth",
            listing_id="listing-eth",
            price=Decimal("50000.0000000000"),
            currency="USD",
            source=PriceSource.yahoo_finance,
            timestamp=datetime(2024, 1, 2),
        ),
    )
    rate = cast(
        ExchangeRateModel,
        SimpleNamespace(
            id="fx",
            rate=Decimal("23.00000000"),
            from_currency="USD",
            to_currency="CZK",
            source=ExchangeRateSource.yahoo_finance,
            date=datetime(2024, 1, 2),
        ),
    )
    with pytest.raises(TransferValuationStateError):
        validate_transfer_valuation_citations(
            evidence=evidence, movement=_movement(), price=price, exchange_rate=rate
        )


def test_prior_day_intraday_selection_is_classified_for_daily_fallback() -> None:
    prior_day_price = SimpleNamespace(
        through=EVENT_AT,
        observation=SimpleNamespace(observed_at=datetime(2024, 1, 1, 23, 30)),
    )
    same_day_rate = SimpleNamespace(
        through=EVENT_AT,
        observation=SimpleNamespace(effective_at=datetime(2024, 1, 2)),
    )
    with pytest.raises(HistoricalMarketEvidenceStateError):
        require_same_day_selections((prior_day_price,), (same_day_rate,))  # type: ignore[arg-type]


def test_prior_business_day_fx_is_accepted_for_weekend_transfer() -> None:
    same_day_price = SimpleNamespace(
        through=EVENT_AT,
        observation=SimpleNamespace(observed_at=datetime(2024, 1, 2)),
    )
    prior_day_rate = SimpleNamespace(
        through=EVENT_AT,
        observation=SimpleNamespace(effective_at=datetime(2024, 1, 1)),
    )
    require_same_day_selections((same_day_price,), (prior_day_rate,))  # type: ignore[arg-type]
