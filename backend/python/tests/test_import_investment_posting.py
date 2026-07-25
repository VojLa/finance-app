from __future__ import annotations

import asyncio
from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import AssetType, ImportRowStatus, ImportSource, ImportStatus, PriceSource
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.imports.classification import InvestmentEventPostingIntent, classify_import_row
from app.modules.imports.investment_asset_resolution import ResolvedInvestmentAsset
from app.modules.imports.investment_posting import (
    ImportInvestmentPostingWriter,
    _movement_signature,
)
from app.modules.imports.investment_posting_plan import build_investment_posting_plan
from app.modules.imports.posting_common import ImportPostStateError


class _Rows:
    def __init__(self, values: Sequence[object]) -> None:
        self.values = list(values)

    def all(self) -> list[object]:
        return self.values


class _Session:
    def __init__(self, *, scalar_values: list[object] | None = None) -> None:
        self.scalar_values = list(scalar_values or [])
        self.scalar = AsyncMock(side_effect=self._scalar)
        self.scalars = AsyncMock(return_value=_Rows([]))
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.begin_nested = MagicMock()
        self.added: list[object] = []

    async def _scalar(self, _: object) -> object:
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value: object) -> None:
        self.added.append(value)


def _batch(*, source: ImportSource = ImportSource.trading212) -> ImportBatchModel:
    return cast(
        ImportBatchModel,
        SimpleNamespace(
            id="batch",
            account_id="account",
            source=source,
            status=ImportStatus.processing,
            rows_total=1,
            rows_imported=0,
            rows_skipped=0,
            completed_at=None,
        ),
    )


def _canonical(action: str = "buy") -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 2,
        "source": "trading212",
        "kind": "investment_event",
        "date": "2026-07-25T10:00:00.123000+00:00",
        "action": action,
        "external_id": "external-1",
        "raw_action": action.replace("_", " "),
        "asset": {
            "symbol": "vwce",
            "isin": "ie00b4l5y983",
            "name": "Vanguard FTSE All-World",
            "asset_type_hint": "ETF",
        },
        "quantity": "2",
        "price": {"amount": "100.5", "currency": "EUR"},
        "total": {"amount": "201", "currency": "EUR"},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": "provider note",
        "order_id": None,
        "asset_direction": None,
    }
    if action == "fee":
        data.update(
            asset={"symbol": None, "isin": None, "name": None, "asset_type_hint": None},
            quantity=None,
            price=None,
            total={"amount": "2", "currency": "EUR"},
        )
    return data


def _row(
    *,
    action: str = "buy",
    status: ImportRowStatus = ImportRowStatus.pending,
) -> ImportRowModel:
    canonical = _canonical(action)
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=canonical)
    assert isinstance(intent, InvestmentEventPostingIntent)
    return cast(
        ImportRowModel,
        SimpleNamespace(
            id="row",
            import_batch_id="batch",
            raw_data={"raw": "preserved"},
            normalized_data={
                **deepcopy(canonical),
                "deduplication": {"schema_version": 1, "status": "unique"},
                "posting_intent": intent.model_dump(mode="json"),
            },
            validation_errors=None,
            deduplication_key="key",
            status=status,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=("event" if status is ImportRowStatus.imported else None),
        ),
    )


def _resolved() -> ResolvedInvestmentAsset:
    asset = AssetModel(
        id="asset",
        symbol="VWCE",
        isin="IE00B4L5Y983",
        name="Vanguard FTSE All-World",
        asset_type=AssetType.etf,
        currency="EUR",
        updated_at=datetime(2026, 7, 25, 10),
    )
    listing = AssetListingModel(
        id="listing",
        asset_id=asset.id,
        symbol="VWCE",
        exchange="trading212",
        mic=None,
        currency="EUR",
        country=None,
        provider=PriceSource.broker,
        provider_symbol="VWCE",
        is_primary=False,
        updated_at=datetime(2026, 7, 25, 10),
    )
    return ResolvedInvestmentAsset(asset, listing, False, False)


def _writer(session: _Session) -> ImportInvestmentPostingWriter:
    return ImportInvestmentPostingWriter(cast(AsyncSession, session))


def _run(coro: object) -> Any:
    return asyncio.run(cast(Any, coro))


def test_pending_write_maps_event_movements_and_transitions_only_after_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.investment_posting as posting

    row, batch = _row(), _batch()
    before_json = deepcopy(row.normalized_data)
    session = _Session(scalar_values=[row])
    resolved = _resolved()

    class _Resolver:
        def __init__(self, _: object) -> None:
            pass

        async def resolve(self, *, plan: object) -> ResolvedInvestmentAsset:
            assert plan is not None
            return resolved

    async def flush() -> None:
        assert row.status is ImportRowStatus.pending

    session.flush.side_effect = flush
    monkeypatch.setattr(posting, "ImportInvestmentAssetResolver", _Resolver)
    monkeypatch.setattr(
        posting, "_current_updated_at", lambda: datetime(2026, 7, 25, 10, 0, 0, 123000)
    )

    result = _run(_writer(session).post_row(account_id="account", batch=batch, row=row))

    assert (
        result.created is True
        and result.asset is resolved.asset
        and result.listing is resolved.listing
    )
    assert result.event.account_id == "account"
    assert result.event.import_batch_id == "batch"
    assert result.event.updated_at.microsecond == 123000
    assert len(result.movements) == 2
    assert [_movement_signature(movement)[4:6] for movement in result.movements] == [
        ("asset", "listing"),
        (None, None),
    ]
    assert all(movement.updated_at == result.event.updated_at for movement in result.movements)
    assert row.status is ImportRowStatus.imported
    assert row.created_transaction_id is None
    assert row.created_investment_event_id == result.event.id
    assert row.normalized_data == before_json
    assert (batch.status, batch.rows_imported, batch.rows_skipped, batch.completed_at) == (
        ImportStatus.processing,
        0,
        0,
        None,
    )
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.begin_nested.assert_not_called()


def test_cash_only_plan_never_calls_asset_resolver_and_has_null_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.investment_posting as posting

    row, batch, session = _row(action="fee"), _batch(), _Session()
    session.scalar.side_effect = [row]

    class _Resolver:
        def __init__(self, _: object) -> None:
            raise AssertionError("cash-only plan must not resolve an asset")

    monkeypatch.setattr(posting, "ImportInvestmentAssetResolver", _Resolver)
    result = _run(_writer(session).post_row(account_id="account", batch=batch, row=row))

    assert result.asset is None and result.listing is None
    assert len(result.movements) == 1
    assert result.movements[0].asset_id is None and result.movements[0].listing_id is None


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_account",
        "non_processing",
        "wrong_batch",
        "duplicate",
        "created_transaction",
        "event_id_pending",
    ],
)
def test_invalid_boundaries_fail_closed_before_write(mutation: str) -> None:
    row, batch = _row(), _batch()
    account_id = "account"
    if mutation == "wrong_account":
        account_id = "foreign"
    elif mutation == "non_processing":
        batch.status = ImportStatus.completed
    elif mutation == "wrong_batch":
        row.import_batch_id = "other"
    elif mutation == "duplicate":
        row.status = ImportRowStatus.duplicate
    elif mutation == "created_transaction":
        row.created_transaction_id = "transaction"
    elif mutation == "event_id_pending":
        row.created_investment_event_id = "event"
    session = _Session(scalar_values=[row])

    with pytest.raises(ImportPostStateError):
        _run(_writer(session).post_row(account_id=account_id, batch=batch, row=row))

    assert session.added == [] and session.flush.await_count == 0


def test_imported_replay_compares_exact_event_and_movement_multiset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.investment_posting as posting

    row, batch = _row(status=ImportRowStatus.imported), _batch()
    plan = build_investment_posting_plan(account_id="account", batch=batch, row=row)
    resolved = _resolved()
    event = InvestmentEventModel(
        id="event",
        account_id=plan.account_id,
        type=plan.event_type,
        date=plan.date,
        source=plan.source,
        external_id=plan.external_id,
        order_id=plan.order_id,
        description=plan.description,
        realized_pnl=plan.realized_pnl,
        realized_pnl_currency=plan.realized_pnl_currency,
        import_batch_id=plan.import_batch_id,
        archived_at=None,
        deleted_at=None,
        created_at=datetime(2026, 7, 25, 10, 0, 0, 123000),
        updated_at=datetime(2026, 7, 25, 10, 0, 0, 123000),
    )
    movements = [
        InvestmentMovementModel(
            id=f"movement-{index}",
            event_id=event.id,
            account_id=plan.account_id,
            asset_id=resolved.asset.id if movement.requires_asset else None,
            listing_id=resolved.listing.id if movement.requires_asset else None,
            kind=movement.kind,
            direction=movement.direction,
            quantity=movement.quantity,
            currency=movement.currency,
            price_per_unit=movement.price_per_unit,
            value_amount=movement.value_amount,
            value_currency=movement.value_currency,
            source_symbol=movement.source_symbol,
            source_asset_type=movement.source_asset_type,
            note=movement.note,
            created_at=datetime(2026, 7, 25, 10, 0, 0, 123000),
            updated_at=datetime(2026, 7, 25, 10, 0, 0, 123000),
        )
        for index, movement in enumerate(plan.movements)
    ]
    session = _Session(scalar_values=[row, event, resolved.asset, resolved.listing])
    session.scalars.return_value = _Rows(movements)

    class _Resolver:
        def __init__(self, _: object) -> None:
            raise AssertionError("replay must not call the B2 creation resolver")

    monkeypatch.setattr(posting, "ImportInvestmentAssetResolver", _Resolver)
    result = _run(_writer(session).post_row(account_id="account", batch=batch, row=row))

    assert (
        result.created is False and result.event is event and result.movements == tuple(movements)
    )
    assert session.added == [] and session.flush.await_count == 0

    session = _Session(scalar_values=[row, event, resolved.asset, resolved.listing])
    session.scalars.return_value = _Rows(movements[:-1])
    monkeypatch.setattr(posting, "ImportInvestmentAssetResolver", _Resolver)
    with pytest.raises(ImportPostStateError):
        _run(_writer(session).post_row(account_id="account", batch=batch, row=row))

    extra = deepcopy(movements[0])
    extra.id = "extra"
    extra.quantity += 1
    for corrupt_movements in ([*movements, movements[0]], [*movements, extra]):
        session = _Session(scalar_values=[row, event, resolved.asset, resolved.listing])
        session.scalars.return_value = _Rows(corrupt_movements)
        with pytest.raises(ImportPostStateError):
            _run(_writer(session).post_row(account_id="account", batch=batch, row=row))

    missing_listing = _Session(scalar_values=[row, event, resolved.asset, None])
    missing_listing.scalars.return_value = _Rows(movements)
    with pytest.raises(ImportPostStateError):
        _run(_writer(missing_listing).post_row(account_id="account", batch=batch, row=row))

    wrong_listing = deepcopy(resolved.listing)
    wrong_listing.asset_id = "other-asset"
    wrong = _Session(scalar_values=[row, event, resolved.asset, wrong_listing])
    wrong.scalars.return_value = _Rows(movements)
    with pytest.raises(ImportPostStateError):
        _run(_writer(wrong).post_row(account_id="account", batch=batch, row=row))


def test_corrupt_replay_event_and_asset_link_are_rejected() -> None:
    row, batch = _row(action="fee", status=ImportRowStatus.imported), _batch()
    session = _Session(scalar_values=[row, None])
    with pytest.raises(ImportPostStateError):
        _run(_writer(session).post_row(account_id="account", batch=batch, row=row))
    assert session.added == []
