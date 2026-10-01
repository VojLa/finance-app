import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MarketDataHealthState,
    MovementDirection,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
from app.modules.investments.models import ManualInvestmentCreateRequest, SymbolPositionResponse
from app.modules.investments.service import (
    InvestmentService,
    _price_freshness,
    _trace_status,
    build_manual_event_plan,
)
from app.modules.market_data.requirements import ResolvedPriceIdentity
from app.modules.market_data.source_policy import LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY


def _request(**values: object) -> ManualInvestmentCreateRequest:
    return ManualInvestmentCreateRequest.model_validate(
        {
            "accountId": "account-1",
            "idempotencyKey": "request-1",
            "date": "2026-08-10",
            **values,
        }
    )


def test_buy_plan_has_exact_asset_cash_and_fee_movements() -> None:
    plan = build_manual_event_plan(
        _request(
            type="buy",
            symbol="vwce",
            name="VWCE",
            assetType="etf",
            quantity="2.5000000000",
            pricePerUnit="100.0000000000",
            priceCurrency="EUR",
            totalAmount="250.0000000000",
            totalCurrency="EUR",
            fee="1.0000000000",
            feeCurrency="EUR",
        )
    )

    assert plan.event_type is InvestmentEventType.trade
    assert plan.asset is not None
    assert plan.asset.symbol == "VWCE"
    assert plan.asset.provider.value == "manual"
    assert tuple((item.kind, item.direction) for item in plan.movements) == (
        (InvestmentMovementKind.asset, MovementDirection.incoming),
        (InvestmentMovementKind.cash, MovementDirection.outgoing),
        (InvestmentMovementKind.fee, MovementDirection.outgoing),
    )
    assert plan.movements[0].quantity == Decimal("2.5000000000")
    assert plan.movements[1].quantity == Decimal("250.0000000000")


def test_conversion_requires_two_exact_cash_legs() -> None:
    plan = build_manual_event_plan(
        _request(
            type="currency_conversion",
            conversionFromAmount="100.0000000000",
            conversionFromCurrency="EUR",
            conversionToAmount="110.0000000000",
            conversionToCurrency="USD",
        )
    )

    assert plan.event_type is InvestmentEventType.currency_conversion
    assert tuple((item.direction, item.currency) for item in plan.movements) == (
        (MovementDirection.outgoing, "EUR"),
        (MovementDirection.incoming, "USD"),
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"type": "buy", "symbol": "VWCE", "assetType": "etf"},
        {"type": "currency_conversion", "totalAmount": "1", "totalCurrency": "EUR"},
        {
            "type": "interest",
            "symbol": "VWCE",
            "assetType": "etf",
            "totalAmount": "1",
            "totalCurrency": "EUR",
        },
        {
            "type": "deposit",
            "symbol": "VWCE",
            "assetType": "etf",
            "quantity": "1",
            "totalAmount": "1",
            "totalCurrency": "EUR",
        },
    ),
)
def test_invalid_or_ambiguous_actions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _request(**payload)


def test_symbol_trace_requires_exact_identity_currency_and_holding_price() -> None:
    as_of = datetime(2026, 9, 30, 12)
    asset = AssetModel(id="asset-1", asset_type=AssetType.stock)
    listing = AssetListingModel(id="listing-1", asset_id="asset-1", currency="EUR")
    holding = HoldingModel(
        asset_id="asset-1",
        listing_id="listing-1",
        currency="EUR",
        asset_type=AssetType.stock,
        current_price=Decimal("10"),
        current_value=Decimal("20"),
    )
    price = PriceSnapshotModel(
        asset_id="asset-1",
        listing_id="listing-1",
        source=PriceSource.yahoo_finance,
        provider_symbol="ABC.DE",
        currency="EUR",
        price=Decimal("10"),
        timestamp=as_of,
    )
    identity = ResolvedPriceIdentity(
        provider=PriceSource.yahoo_finance, provider_symbol="ABC.DE", price_currency="EUR"
    )

    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "ok"
    )
    holding.current_price = Decimal("9")
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "ok"
    )
    holding.current_price = Decimal("10")
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=None,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "unresolved"
    )
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=None,
            conflicting_price=False,
            as_of=as_of,
        )
        == "unavailable"
    )

    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=None,
            conflicting_price=True,
            as_of=as_of,
        )
        == "conflict"
    )

    price.provider_symbol = "OTHER.DE"
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "conflict"
    )
    price.provider_symbol = None
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "unavailable"
    )

    price.provider_symbol = "ABC.DE"
    price.currency = "USD"
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "conflict"
    )
    price.currency = "EUR"
    price.timestamp = as_of - timedelta(days=4)
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "stale"
    )
    price.timestamp = as_of
    converted_identity = ResolvedPriceIdentity(
        provider=PriceSource.yahoo_finance, provider_symbol="ABC.DE", price_currency="USD"
    )
    price.currency = "USD"
    assert (
        _trace_status(
            holding=holding,
            listing=listing,
            asset=asset,
            identity=converted_identity,
            price=price,
            conflicting_price=False,
            as_of=as_of,
        )
        == "unavailable"
    )


def test_symbol_position_serializes_unknown_cost_basis() -> None:
    position = SymbolPositionResponse(
        id="holding-1",
        account_id="account-1",
        account_name="Broker",
        asset_id="asset-1",
        listing_id="listing-1",
        symbol="ABC",
        name="ABC",
        asset_type=AssetType.stock,
        quantity=Decimal("2"),
        avg_buy_price=None,
        currency="EUR",
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        calculated_at=datetime(2026, 9, 30),
        asset_name="ABC",
        asset_isin=None,
        listing_symbol="ABC",
        listing_exchange=None,
        listing_mic=None,
        listing_currency="EUR",
        listing_base_priority=0,
        requested_listing_id="listing-1",
        selected_listing_id=None,
        selection_reason=None,
        fallback_reason=None,
        selected_base_priority=None,
        selected_health=None,
        selected_provider=None,
        selected_provider_symbol=None,
        market_provider=None,
        market_provider_symbol=None,
        price_amount=None,
        price_currency=None,
        price_timestamp=None,
        price_source=None,
        price_provider_symbol=None,
        price_snapshot_id=None,
        price_freshness="unavailable",
        fx_evidence_id=None,
        fx_rate=None,
        converted_value=None,
        trace_status="unresolved",
    )

    assert position.model_dump(by_alias=True, mode="json")["avgBuyPrice"] is None
    assert position.model_dump(by_alias=True, mode="json")["fxEvidenceId"] is None


@pytest.mark.parametrize(
    (
        "preferred_health",
        "fallback_asset_id",
        "fallback_currency",
        "fallback_health_symbol",
        "fallback_age_days",
        "preferred_age_days",
        "expected_listing",
        "expected_fallback",
    ),
    (
        (
            MarketDataHealthState.degraded,
            "asset",
            "EUR",
            None,
            0,
            0,
            "fallback",
            "requested_listing_degraded",
        ),
        (MarketDataHealthState.healthy, "asset", "EUR", None, 0, 0, "preferred", None),
        (MarketDataHealthState.degraded, "foreign", "EUR", None, 0, 0, "preferred", None),
        (MarketDataHealthState.degraded, "asset", "USD", None, 0, 0, "preferred", None),
        (MarketDataHealthState.degraded, "asset", "EUR", "WRONG", 0, 0, "preferred", None),
        (MarketDataHealthState.degraded, "asset", "EUR", None, 4, 0, "preferred", None),
        (
            MarketDataHealthState.healthy,
            "asset",
            "EUR",
            None,
            0,
            4,
            "fallback",
            "requested_price_unavailable",
        ),
    ),
)
def test_symbol_trace_uses_exact_fresh_selected_listing(
    preferred_health: MarketDataHealthState,
    fallback_asset_id: str,
    fallback_currency: str,
    fallback_health_symbol: str | None,
    fallback_age_days: int,
    preferred_age_days: int,
    expected_listing: str,
    expected_fallback: str | None,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    asset = AssetModel(id="asset", symbol="ABC", asset_type=AssetType.stock, currency="EUR")
    preferred = AssetListingModel(
        id="preferred",
        asset_id=asset.id,
        symbol="ABC",
        currency="EUR",
        provider=PriceSource.yahoo_finance,
        provider_symbol="ABC.DE",
        base_priority=10,
    )
    fallback = AssetListingModel(
        id="fallback",
        asset_id=fallback_asset_id,
        symbol="ABC",
        currency=fallback_currency,
        provider=PriceSource.yahoo_finance,
        provider_symbol="ABC.AS",
        base_priority=5,
    )
    holding = HoldingModel(
        id="holding",
        account_id="account",
        asset_id=asset.id,
        listing_id=preferred.id,
        symbol="ABC",
        asset_type=AssetType.stock,
        currency="EUR",
        quantity=Decimal("2"),
        current_price=Decimal("11"),
        current_value=Decimal("22"),
        calculated_at=now,
    )
    prices = {
        "preferred": PriceSnapshotModel(
            id="preferred-price",
            asset_id=asset.id,
            listing_id=preferred.id,
            source=PriceSource.yahoo_finance,
            provider_symbol="ABC.DE",
            currency="EUR",
            price=Decimal("11"),
            timestamp=now - timedelta(days=preferred_age_days),
        ),
        "fallback": PriceSnapshotModel(
            id="fallback-price",
            asset_id=fallback_asset_id,
            listing_id=fallback.id,
            source=PriceSource.yahoo_finance,
            provider_symbol="ABC.AS",
            currency=fallback_currency,
            price=Decimal("12"),
            timestamp=now - timedelta(days=fallback_age_days),
        ),
    }

    class PriceRepository:
        async def exact_price(self, **query: object) -> tuple[PriceSnapshotModel | None, bool]:
            candidate = prices[str(query["listing_id"])]
            return (
                candidate
                if candidate.asset_id == query["asset_id"]
                and candidate.source == query["source"]
                and candidate.provider_symbol == query["provider_symbol"]
                and candidate.currency == query["currency"]
                else None,
                False,
            )

    service = InvestmentService(None)  # type: ignore[arg-type]
    service.repository = PriceRepository()  # type: ignore[assignment]
    result = asyncio.run(
        service._position_response(
            holding=holding,
            account_name="Broker",
            listing=preferred,
            asset=asset,
            aliases=(),
            candidate_listings=(preferred, fallback),
            health_by_identity={
                (preferred.id, PriceSource.yahoo_finance): MarketDataListingHealthModel(
                    provider_symbol="ABC.DE", state=preferred_health, retry_after=None
                ),
                (fallback.id, PriceSource.yahoo_finance): MarketDataListingHealthModel(
                    provider_symbol=fallback_health_symbol or "ABC.AS",
                    state=MarketDataHealthState.healthy,
                    retry_after=None,
                ),
            },
            provider_retry_after={},
            source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        )
    )
    trace = result.model_dump(by_alias=True, mode="json")
    assert trace["requestedListingId"] == "preferred"
    assert trace["listingId"] == "preferred"
    assert trace["selectedListingId"] == expected_listing
    assert trace["fallbackReason"] == expected_fallback
    assert trace["priceSnapshotId"] == f"{expected_listing}-price"
    assert trace["priceFreshness"] == "fresh"
    assert trace["selectedProviderSymbol"] == prices[expected_listing].provider_symbol
    assert trace["marketProviderSymbol"] == "ABC.DE"
    assert trace["traceStatus"] == "ok"
    assert trace["fxEvidenceId"] is None
    assert trace["convertedValue"] is None


def test_symbol_trace_freshness_uses_supported_market_previous_close_only() -> None:
    as_of = datetime(2026, 9, 7, 23)  # US Labor Day, after the Friday close.
    price = PriceSnapshotModel(timestamp=datetime(2026, 9, 4, 20))
    supported = AssetListingModel(mic="XNAS")
    unknown = AssetListingModel(mic="UNKN")

    assert (
        _price_freshness(price=price, listing=supported, asset_type="stock", as_of=as_of) == "fresh"
    )
    assert (
        _price_freshness(price=price, listing=unknown, asset_type="stock", as_of=as_of) == "stale"
    )
    assert (
        _price_freshness(price=price, listing=supported, asset_type="crypto", as_of=as_of)
        == "stale"
    )
