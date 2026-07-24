from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import AssetType, PriceSource
from app.modules.imports.investment_asset_resolution import (
    ImportInvestmentAssetResolver,
    advisory_lock_id,
)
from app.modules.imports.investment_posting_plan import InvestmentAssetResolutionPlan
from app.modules.imports.posting_common import ImportPostStateError


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _Session:
    def __init__(
        self,
        *,
        query_rows: list[list[object]] | None = None,
        scalar_rows: list[list[object]] | None = None,
    ) -> None:
        self.query_rows = list(query_rows or [])
        self.scalar_rows = list(scalar_rows or [])
        self.locks: list[int] = []
        self.events: list[str] = []
        self.added: list[object] = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.begin_nested = MagicMock()

    async def execute(self, statement: object) -> _Rows:
        rendered = str(statement)
        if "pg_advisory_xact_lock" in rendered:
            params = cast(Any, statement).compile().params
            self.locks.append(next(iter(params.values())))
            self.events.append("lock")
            return _Rows([])
        self.events.append("lookup")
        return _Rows(self.query_rows.pop(0) if self.query_rows else [])

    async def scalars(self, statement: object) -> _Rows:
        self.events.append("lookup")
        return _Rows(self.scalar_rows.pop(0) if self.scalar_rows else [])

    def add(self, item: object) -> None:
        self.added.append(item)


def _plan(**overrides: object) -> InvestmentAssetResolutionPlan:
    values: dict[str, object] = {
        "symbol": "VWCE",
        "isin": "IE00B4L5Y983",
        "name": "Vanguard FTSE All-World",
        "asset_type": AssetType.etf,
        "provider": PriceSource.broker,
        "provider_symbol": "VWCE",
        "exchange": "trading212",
        "listing_currency_hint": "EUR",
        "asset_currency_hint": "EUR",
    }
    values.update(overrides)
    return InvestmentAssetResolutionPlan(**values)  # type: ignore[arg-type]


def _resolver(session: _Session) -> ImportInvestmentAssetResolver:
    return ImportInvestmentAssetResolver(cast(AsyncSession, session))


def _asset(
    *,
    asset_id: str = "asset-1",
    symbol: str = "VWCE",
    isin: str | None = "IE00B4L5Y983",
    asset_type: AssetType = AssetType.etf,
    currency: str = "EUR",
) -> AssetModel:
    return AssetModel(
        id=asset_id,
        symbol=symbol,
        isin=isin,
        name="Existing",
        asset_type=asset_type,
        currency=currency,
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _listing(
    asset: AssetModel,
    *,
    listing_id: str = "listing-1",
    symbol: str = "VWCE",
    exchange: str = "trading212",
    currency: str = "EUR",
    provider: PriceSource = PriceSource.broker,
    provider_symbol: str = "VWCE",
) -> AssetListingModel:
    return AssetListingModel(
        id=listing_id,
        asset_id=asset.id,
        symbol=symbol,
        exchange=exchange,
        mic=None,
        currency=currency,
        country=None,
        provider=provider,
        provider_symbol=provider_symbol,
        is_primary=False,
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )


def test_advisory_lock_ids_use_repository_signed_sha256_contract() -> None:
    scope = "assets:provider:broker:VWCE"
    assert advisory_lock_id(scope) == int.from_bytes(
        __import__("hashlib").sha256(scope.encode()).digest()[:8], "big", signed=True
    )
    assert advisory_lock_id("assets:isin:IE00B4L5Y983") != advisory_lock_id(scope)


def test_locks_are_sorted_deduplicated_and_acquired_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.investment_asset_resolution as resolution

    monkeypatch.setattr(resolution, "advisory_lock_id", lambda scope: 7 if "isin" in scope else -2)
    session = _Session(query_rows=[[]])

    asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert session.locks == [-2, 7]
    assert session.events[:3] == ["lock", "lock", "lookup"]


def test_duplicate_lock_ids_are_acquired_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.imports.investment_asset_resolution as resolution

    monkeypatch.setattr(resolution, "advisory_lock_id", lambda scope: 1)
    session = _Session(query_rows=[[]])

    asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert session.locks == [1]


def test_divergent_provider_symbol_is_rejected_before_locks_or_lookups() -> None:
    session = _Session()

    with pytest.raises(ImportPostStateError):
        asyncio_run(
            _resolver(session).resolve(plan=_plan(symbol="VWCE", provider_symbol="VWCE_US"))
        )

    assert session.locks == []
    assert session.events == []
    assert session.added == []
    assert session.flush.await_count == 0


def test_new_pair_truncates_updated_at_to_canonical_timestamp_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.investment_asset_resolution as resolution

    controlled_now = datetime(2026, 7, 24, 12, 0, 0, 123456, tzinfo=UTC)
    normalize_timestamp = resolution._current_updated_at
    monkeypatch.setattr(
        resolution,
        "_current_updated_at",
        lambda: normalize_timestamp(controlled_now),
    )
    session = _Session(query_rows=[[], [], []], scalar_rows=[[]])

    result = asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert result.asset.updated_at == datetime(2026, 7, 24, 12, 0, 0, 123000)
    assert result.listing.updated_at == result.asset.updated_at
    assert result.asset.updated_at.microsecond % 1000 == 0


def test_exact_provider_listing_is_preferred_without_mutation() -> None:
    asset = _asset()
    listing = _listing(asset)
    session = _Session(query_rows=[[(listing, asset)]])

    result = asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert result.asset is asset and result.listing is listing
    assert result.asset_created is False and result.listing_created is False
    assert session.added == [] and session.flush.await_count == 0


def test_currencyless_plan_reuses_one_provider_listing_but_rejects_ambiguity() -> None:
    asset = _asset()
    listing = _listing(asset)
    unique_session = _Session(query_rows=[[(listing, asset)]])
    plan = _plan(listing_currency_hint=None, asset_currency_hint=None)
    unique = asyncio_run(_resolver(unique_session).resolve(plan=plan))
    assert unique.listing is listing

    ambiguous_session = _Session(
        query_rows=[[(listing, asset), (_listing(asset, listing_id="two"), asset)]]
    )
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(ambiguous_session).resolve(plan=plan))


def test_other_plan_accepts_existing_specific_type_but_specific_conflict_fails() -> None:
    asset = _asset(asset_type=AssetType.etf)
    listing = _listing(asset)
    other_session = _Session(query_rows=[[(listing, asset)]])
    assert (
        asyncio_run(_resolver(other_session).resolve(plan=_plan(asset_type=AssetType.other))).asset
        is asset
    )

    conflict_session = _Session(query_rows=[[(listing, asset)]])
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(conflict_session).resolve(plan=_plan(asset_type=AssetType.stock)))


def test_provider_listing_currency_and_isin_conflicts_fail_closed() -> None:
    currency_asset = _asset(currency="USD")
    currency_session = _Session(query_rows=[[(_listing(currency_asset), currency_asset)]])
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(currency_session).resolve(plan=_plan()))

    isin_asset = _asset(isin="OTHER")
    isin_session = _Session(query_rows=[[(_listing(isin_asset), isin_asset)]])
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(isin_session).resolve(plan=_plan()))


def test_unique_isin_asset_creates_only_listing_and_replay_is_exact() -> None:
    asset = _asset(symbol="OLD-SYMBOL")
    session = _Session(query_rows=[[], [], [], []], scalar_rows=[[asset]])

    result = asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert result.asset is asset
    assert result.asset_created is False and result.listing_created is True
    assert len(session.added) == 1 and isinstance(session.added[0], AssetListingModel)
    assert session.flush.await_count == 1

    replay_listing = result.listing
    replay_session = _Session(query_rows=[[(replay_listing, asset)]])
    replay = asyncio_run(_resolver(replay_session).resolve(plan=_plan()))
    assert replay.asset.id == asset.id and replay.listing.id == replay_listing.id
    assert replay.asset_created is False and replay.listing_created is False


def test_multiple_isin_assets_are_ambiguous() -> None:
    session = _Session(
        query_rows=[[]], scalar_rows=[[_asset(asset_id="one"), _asset(asset_id="two")]]
    )
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(session).resolve(plan=_plan()))


def test_missing_evidence_rejects_without_symbol_only_lookup() -> None:
    session = _Session(query_rows=[[]], scalar_rows=[])
    with pytest.raises(ImportPostStateError):
        asyncio_run(
            _resolver(session).resolve(
                plan=_plan(isin=None, listing_currency_hint=None, asset_currency_hint=None)
            )
        )
    assert session.events.count("lookup") == 1
    assert session.added == []


def test_new_asset_listing_mapping_does_not_merge_by_symbol() -> None:
    session = _Session(query_rows=[[], [], [], []], scalar_rows=[[]])

    result = asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert result.asset_created is True and result.listing_created is True
    assert len(session.added) == 2
    assert isinstance(session.added[0], AssetModel)
    assert isinstance(session.added[1], AssetListingModel)
    assert result.asset.symbol == "VWCE" and result.listing.provider_symbol == "VWCE"
    assert session.flush.await_count == 1


def test_conflicting_provider_and_market_identities_fail_closed() -> None:
    asset = _asset()
    provider = _listing(asset, listing_id="provider", symbol="OTHER")
    market = _listing(asset, listing_id="market")
    session = _Session(query_rows=[[], [(provider, asset)], [(market, asset)]], scalar_rows=[[]])
    with pytest.raises(ImportPostStateError):
        asyncio_run(_resolver(session).resolve(plan=_plan()))
    assert session.added == []


@pytest.mark.parametrize(
    "plan",
    [
        _plan(symbol=" "),
        _plan(provider_symbol="lower"),
        _plan(exchange="other"),
        _plan(provider=PriceSource.manual),
        _plan(provider=PriceSource.exchange, exchange="anycoin", asset_type=AssetType.stock),
    ],
)
def test_invalid_plan_boundary_is_generic_and_does_not_lookup(
    plan: InvestmentAssetResolutionPlan,
) -> None:
    session = _Session()
    with pytest.raises(ImportPostStateError) as error:
        asyncio_run(_resolver(session).resolve(plan=plan))
    assert str(error.value) == "The import batch is not available for posting."
    assert session.events == []


def test_resolver_never_commits_rolls_back_or_touches_import_state() -> None:
    asset = _asset()
    listing = _listing(asset)
    session = _Session(query_rows=[[(listing, asset)]])
    batch = SimpleNamespace(status="processing", rows_total=1, rows_imported=0)
    row = SimpleNamespace(
        status="pending", created_transaction_id=None, created_investment_event_id=None
    )
    before = (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        row.status,
        row.created_transaction_id,
    )

    asyncio_run(_resolver(session).resolve(plan=_plan()))

    assert session.commit.await_count == 0 and session.rollback.await_count == 0
    assert session.begin_nested.call_count == 0
    assert before == (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        row.status,
        row.created_transaction_id,
    )


def asyncio_run(awaitable: object):
    import asyncio

    return asyncio.run(awaitable)  # type: ignore[arg-type]
