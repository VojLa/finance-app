from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType as DbAccountType,
)
from app.db.models.enums import (
    AssetType as DbAssetType,
)
from app.db.models.enums import (
    PriceSource,
)
from app.db.models.enums import (
    SnapshotGranularity as DbSnapshotGranularity,
)
from app.db.models.enums import (
    SnapshotSource as DbSnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.portfolio_snapshot.currency_breakdown import (
    PortfolioCurrencyBreakdownError,
    decode_portfolio_currency_breakdown,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioCurrencyAmount,
    PortfolioSnapshotSource,
    SnapshotGranularity,
)
from app.modules.portfolio_snapshot.projection import build_portfolio_snapshot_view
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    PortfolioSnapshotReader,
    PortfolioSnapshotReadError,
    ReadExactPortfolioSnapshotCommand,
)
from app.modules.portfolio_snapshot.repository import PersistedPortfolioSnapshotItem

SNAPSHOT_AT = datetime(2032, 8, 2)
CALCULATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 456000)
MODULE_DIR = Path(__file__).parents[1] / "app" / "modules" / "portfolio_snapshot"


class FakeSession:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()

    def in_transaction(self) -> bool:
        return self.active


@pytest.mark.parametrize(
    ("physical", "scalar", "expected"),
    [
        ({}, Decimal("0.000000"), ()),
        (
            {"CZK": "123.450000"},
            Decimal("123.450000"),
            (PortfolioCurrencyAmount("CZK", Decimal("123.450000")),),
        ),
        (
            {"USD": "-2.000000", "CZK": "0.000000", "EUR": "3.000000"},
            Decimal("999.000000"),
            (
                PortfolioCurrencyAmount("CZK", Decimal("0.000000")),
                PortfolioCurrencyAmount("EUR", Decimal("3.000000")),
                PortfolioCurrencyAmount("USD", Decimal("-2.000000")),
            ),
        ),
        (
            {"EUR": "-500.000000"},
            Decimal("-500.000000"),
            (PortfolioCurrencyAmount("EUR", Decimal("-500.000000")),),
        ),
    ],
)
def test_currency_breakdown_decoder_accepts_only_canonical_evidence(
    physical: object,
    scalar: Decimal,
    expected: tuple[PortfolioCurrencyAmount, ...],
) -> None:
    assert (
        decode_portfolio_currency_breakdown(
            physical,
            scalar_total=scalar,
            output_currency="CZK" if len(expected) != 1 else expected[0].currency,
        )
        == expected
    )


@pytest.mark.parametrize(
    "physical",
    [
        None,
        [],
        {"czk": "1.000000"},
        {" CZK": "1.000000"},
        {"CZ": "1.000000"},
        {"CZKK": "1.000000"},
        {"CZK": 1.0},
        {"CZK": 1},
        {"CZK": True},
        {"CZK": None},
        {"CZK": []},
        {"CZK": {"amount": "1.000000"}},
        {"CZK": "NaN"},
        {"CZK": "Infinity"},
        {"CZK": "-Infinity"},
        {"CZK": "1e2"},
        {"CZK": "1.0"},
        {"CZK": "1.0000000"},
        {"CZK": " 1.000000"},
        {"CZK": "+1.000000"},
        {"CZK": "01.000000"},
        {"CZK": "1000000000000.000000"},
        {1: "1.000000"},
    ],
)
def test_currency_breakdown_decoder_rejects_noncanonical_physical_values(
    physical: object,
) -> None:
    with pytest.raises(PortfolioCurrencyBreakdownError):
        decode_portfolio_currency_breakdown(
            physical,
            scalar_total=Decimal("1.000000"),
            output_currency="CZK",
        )


def test_currency_breakdown_decoder_enforces_empty_and_same_currency_coherence() -> None:
    with pytest.raises(PortfolioCurrencyBreakdownError):
        decode_portfolio_currency_breakdown(
            {},
            scalar_total=Decimal("1.000000"),
            output_currency="CZK",
        )
    with pytest.raises(PortfolioCurrencyBreakdownError):
        decode_portfolio_currency_breakdown(
            {"CZK": "2.000000"},
            scalar_total=Decimal("1.000000"),
            output_currency="CZK",
        )


class FakeRepository:
    def __init__(
        self,
        *,
        isolation: str | None = "repeatable read",
        account: AccountModel | None = None,
        snapshots: tuple[AccountSnapshotModel, ...] | None = None,
        items: tuple[PersistedPortfolioSnapshotItem, ...] | None = None,
    ) -> None:
        self.isolation = isolation
        self.account: AccountModel | None = account if account is not None else _account()
        self.snapshots = snapshots if snapshots is not None else (_snapshot(),)
        self.items = items if items is not None else _items()
        self.isolation_calls = 0
        self.account_calls = 0
        self.snapshot_calls = 0
        self.item_calls = 0
        self.snapshot_arguments: dict[str, object] | None = None

    async def load_transaction_isolation(self) -> str | None:
        self.isolation_calls += 1
        return self.isolation

    async def load_account(self, account_id: str) -> AccountModel | None:
        self.account_calls += 1
        return self.account

    async def load_exact_snapshots(self, **kwargs: object) -> tuple[AccountSnapshotModel, ...]:
        self.snapshot_calls += 1
        self.snapshot_arguments = kwargs
        return self.snapshots

    async def load_snapshot_items(
        self,
        snapshot_id: str,
    ) -> tuple[PersistedPortfolioSnapshotItem, ...]:
        self.item_calls += 1
        return self.items


def _account(
    *,
    account_id: str = "account-1",
    account_type: DbAccountType = DbAccountType.broker,
) -> AccountModel:
    return AccountModel(
        id=account_id,
        name="Primary account",
        type=account_type,
        currency="CZK",
        color=None,
        is_archived=False,
        archived_at=None,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
        notes=None,
    )


def _snapshot(
    *,
    snapshot_id: str = "snapshot-1",
    account_id: str = "account-1",
    source: DbSnapshotSource = DbSnapshotSource.manual_recalculation,
    is_recalculated: bool = True,
    cash_value: Decimal = Decimal("10"),
    investment_value: Decimal = Decimal("100"),
    investment_cost_basis: Decimal = Decimal("80"),
    liabilities_value: Decimal = Decimal("0"),
    total_value: Decimal = Decimal("110"),
    net_deposits_value: Decimal = Decimal("70"),
    realized_pnl_value: Decimal = Decimal("5"),
    unrealized_pnl_value: Decimal = Decimal("20"),
    fees_value: Decimal = Decimal("2"),
    taxes_value: Decimal = Decimal("1"),
) -> AccountSnapshotModel:
    return AccountSnapshotModel(
        id=snapshot_id,
        account_id=account_id,
        timestamp=SNAPSHOT_AT,
        granularity=DbSnapshotGranularity.day,
        source=source,
        currency="EUR",
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=total_value,
        is_recalculated=is_recalculated,
        calculated_at=CALCULATED_AT,
        calculation_version=1,
        created_at=CREATED_AT,
        net_deposits_value=net_deposits_value,
        realized_pnl_value=realized_pnl_value,
        unrealized_pnl_value=unrealized_pnl_value,
        fees_value=fees_value,
        taxes_value=taxes_value,
        cash_value_by_currency={"EUR": format(cash_value, ".6f")},
        investment_value_by_currency=None,
        investment_cost_basis_by_currency=None,
        net_deposits_by_currency={"EUR": format(net_deposits_value, ".6f")},
        realized_pnl_by_currency=None,
        unrealized_pnl_by_currency=None,
        fees_by_currency=None,
        taxes_by_currency=None,
        exchange_rates=None,
    )


def _asset(
    *,
    asset_id: str,
    symbol: str,
    name: str,
    asset_type: DbAssetType,
    currency: str,
) -> AssetModel:
    return AssetModel(
        id=asset_id,
        symbol=symbol,
        isin=None,
        name=name,
        asset_type=asset_type,
        currency=currency,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _listing(
    *,
    listing_id: str,
    asset_id: str,
    symbol: str,
    currency: str,
) -> AssetListingModel:
    return AssetListingModel(
        id=listing_id,
        asset_id=asset_id,
        symbol=symbol,
        exchange=None,
        mic=None,
        currency=currency,
        country=None,
        provider=PriceSource.manual,
        provider_symbol=None,
        is_primary=True,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _item(
    *,
    item_id: str,
    listing_id: str,
    asset_id: str | None,
    symbol: str,
    quantity: Decimal,
    price_per_unit: Decimal,
    native_currency: str | None,
    value: Decimal,
    cost_basis: Decimal | None,
    allocation_pct: Decimal,
    native_cost_currency: str | None,
) -> AccountSnapshotItemModel:
    return AccountSnapshotItemModel(
        id=item_id,
        snapshot_id="snapshot-1",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol=symbol,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=native_currency,
        price_source=PriceSource.manual,
        price_timestamp=SNAPSHOT_AT,
        value=value,
        cost_basis=cost_basis,
        cost_currency="EUR",
        allocation_pct=allocation_pct,
        created_at=CREATED_AT,
        native_value=quantity * price_per_unit,
        value_currency=native_currency,
        native_cost_basis=cost_basis,
        native_cost_currency=native_cost_currency,
    )


def _persisted(
    *,
    item_id: str,
    listing_id: str,
    asset_id: str,
    symbol: str,
    name: str,
    asset_type: DbAssetType,
    quantity: Decimal,
    price_per_unit: Decimal,
    native_currency: str,
    value: Decimal,
    cost_basis: Decimal,
    allocation_pct: Decimal,
) -> PersistedPortfolioSnapshotItem:
    return PersistedPortfolioSnapshotItem(
        item=_item(
            item_id=item_id,
            listing_id=listing_id,
            asset_id=asset_id,
            symbol=symbol,
            quantity=quantity,
            price_per_unit=price_per_unit,
            native_currency=native_currency,
            value=value,
            cost_basis=cost_basis,
            allocation_pct=allocation_pct,
            native_cost_currency=native_currency,
        ),
        listing=_listing(
            listing_id=listing_id,
            asset_id=asset_id,
            symbol=symbol,
            currency=native_currency,
        ),
        asset=_asset(
            asset_id=asset_id,
            symbol=symbol,
            name=name,
            asset_type=asset_type,
            currency=native_currency,
        ),
    )


def _items() -> tuple[PersistedPortfolioSnapshotItem, ...]:
    return (
        _persisted(
            item_id="item-2",
            listing_id="listing-2",
            asset_id="asset-2",
            symbol="BBB",
            name="Beta asset",
            asset_type=DbAssetType.crypto,
            quantity=Decimal("4"),
            price_per_unit=Decimal("10"),
            native_currency="GBP",
            value=Decimal("40"),
            cost_basis=Decimal("30"),
            allocation_pct=Decimal("40"),
        ),
        _persisted(
            item_id="item-1",
            listing_id="listing-1",
            asset_id="asset-1",
            symbol="AAA",
            name="Alpha asset",
            asset_type=DbAssetType.stock,
            quantity=Decimal("2"),
            price_per_unit=Decimal("30"),
            native_currency="USD",
            value=Decimal("60"),
            cost_basis=Decimal("50"),
            allocation_pct=Decimal("60"),
        ),
    )


def _command(**changes: object) -> ReadExactPortfolioSnapshotCommand:
    values: dict[str, object] = {
        "account_id": "account-1",
        "timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "currency": "EUR",
        "calculation_version": 1,
    }
    values.update(changes)
    return ReadExactPortfolioSnapshotCommand(**cast(Any, values))


def _reader(
    repository: FakeRepository,
    *,
    session: FakeSession | None = None,
    projection_builder: Any = build_portfolio_snapshot_view,
) -> tuple[PortfolioSnapshotReader, FakeSession]:
    resolved_session = session or FakeSession()
    return (
        PortfolioSnapshotReader(
            cast(Any, resolved_session),
            repository=cast(Any, repository),
            projection_builder=projection_builder,
        ),
        resolved_session,
    )


@pytest.mark.asyncio
async def test_exact_investment_snapshot_builds_portfolio_view() -> None:
    repository = FakeRepository()
    reader, _ = _reader(repository)

    result = await reader.read(_command())

    assert result.selected_snapshot_id == "snapshot-1"
    assert result.selected_item_ids == ("item-1", "item-2")
    assert result.view.account.account_id == "account-1"
    assert result.view.account.currency == "CZK"
    assert result.view.currency == "EUR"
    assert result.view.summary.total_value == Decimal("110")
    assert result.view.summary.cash_by_currency == (
        PortfolioCurrencyAmount("EUR", Decimal("10.000000")),
    )
    assert result.view.summary.net_deposits_by_currency == (
        PortfolioCurrencyAmount("EUR", Decimal("70.000000")),
    )
    assert tuple(position.symbol for position in result.view.positions) == ("BBB", "AAA")
    assert repository.snapshot_arguments == {
        "account_id": "account-1",
        "timestamp": SNAPSHOT_AT,
        "granularity": DbSnapshotGranularity.day,
        "currency": "EUR",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "physical"),
    [
        ("cash_value_by_currency", None),
        ("cash_value_by_currency", {}),
        ("cash_value_by_currency", {"EUR": "10.0"}),
        ("cash_value_by_currency", {"EUR": 10.0}),
        ("net_deposits_by_currency", None),
        ("net_deposits_by_currency", {"EUR": "999.000000"}),
    ],
)
async def test_reader_rejects_missing_or_malformed_breakdown_without_fallback(
    field: str,
    physical: object,
) -> None:
    snapshot = _snapshot()
    setattr(snapshot, field, physical)
    reader, _ = _reader(FakeRepository(snapshots=(snapshot,)))

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(_command())


@pytest.mark.asyncio
async def test_exact_liability_snapshot_builds_summary_only_view() -> None:
    account = _account(account_type=DbAccountType.loan)
    snapshot = _snapshot(
        cash_value=Decimal(0),
        investment_value=Decimal(0),
        investment_cost_basis=Decimal(0),
        liabilities_value=Decimal("25"),
        total_value=Decimal("-25"),
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=Decimal(0),
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
    )
    reader, _ = _reader(FakeRepository(account=account, snapshots=(snapshot,), items=()))

    result = await reader.read(_command())

    assert result.view.positions == ()
    assert result.view.summary.liabilities_value == Decimal("25")
    assert result.view.summary.total_value == Decimal("-25")


@pytest.mark.asyncio
async def test_empty_investment_snapshot_builds_empty_view() -> None:
    snapshot = _snapshot(
        investment_value=Decimal(0),
        investment_cost_basis=Decimal(0),
        total_value=Decimal("10"),
        unrealized_pnl_value=Decimal(0),
    )
    reader, _ = _reader(FakeRepository(snapshots=(snapshot,), items=()))

    result = await reader.read(_command())

    assert result.view.positions == ()
    assert result.view.summary.position_count == 0


@pytest.mark.asyncio
async def test_reader_maps_physical_currencies_and_derives_unrealized_pnl_exactly() -> None:
    reader, _ = _reader(FakeRepository())

    result = await reader.read(_command())
    alpha = next(position for position in result.view.positions if position.symbol == "AAA")

    assert alpha.price_currency == "USD"
    assert alpha.native_value_currency == "USD"
    assert alpha.value_currency == "EUR"
    assert alpha.cost_currency == "EUR"
    assert alpha.native_cost_currency == "USD"
    assert alpha.unrealized_pnl == Decimal("10")


@pytest.mark.asyncio
async def test_required_snapshot_id_must_match() -> None:
    reader, _ = _reader(FakeRepository())

    matched = await reader.read(_command(required_snapshot_id="snapshot-1"))
    assert matched.selected_snapshot_id == "snapshot-1"

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(_command(required_snapshot_id="snapshot-other"))


@pytest.mark.asyncio
async def test_reader_never_selects_latest_or_fallback_snapshot() -> None:
    repository = FakeRepository(snapshots=())
    reader, _ = _reader(repository)

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(_command(timestamp=datetime(2032, 8, 3)))

    assert repository.snapshot_calls == 1
    assert repository.snapshot_arguments == {
        "account_id": "account-1",
        "timestamp": datetime(2032, 8, 3),
        "granularity": DbSnapshotGranularity.day,
        "currency": "EUR",
    }


@pytest.mark.asyncio
async def test_reader_calls_projection_exactly_once() -> None:
    calls: list[PortfolioSnapshotSource] = []

    def projection(source: PortfolioSnapshotSource):
        calls.append(source)
        return build_portfolio_snapshot_view(source)

    reader, _ = _reader(FakeRepository(), projection_builder=projection)
    await reader.read(_command())

    assert len(calls) == 1
    assert all(not isinstance(value, AccountSnapshotModel) for value in calls[0].items)


@pytest.mark.asyncio
async def test_reader_does_not_mutate_inputs_and_result_is_frozen() -> None:
    command = _command()
    repository = FakeRepository()
    original_items = repository.items
    reader, _ = _reader(repository)

    result = await reader.read(command)

    assert command == _command()
    assert repository.items == original_items
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).selected_snapshot_id = "changed"
    assert isinstance(result, CompletePortfolioSnapshotRead)


@pytest.mark.asyncio
async def test_reader_requires_active_transaction() -> None:
    repository = FakeRepository()
    reader, _ = _reader(repository, session=FakeSession(active=False))

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(_command())

    assert repository.isolation_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "isolation",
    ["repeatable read", "REPEATABLE_READ", "serializable", "SERIALIZABLE"],
)
async def test_reader_accepts_coherent_isolation(isolation: str) -> None:
    reader, _ = _reader(FakeRepository(isolation=isolation))
    assert (await reader.read(_command())).selected_snapshot_id == "snapshot-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "isolation",
    [None, "", "read committed", "READ_COMMITTED", "read uncommitted"],
)
async def test_reader_rejects_incoherent_isolation(isolation: str | None) -> None:
    repository = FakeRepository(isolation=isolation)
    reader, _ = _reader(repository)

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(_command())

    assert repository.account_calls == 0


@pytest.mark.asyncio
async def test_reader_does_not_commit_or_rollback() -> None:
    reader, session = _reader(FakeRepository())
    await reader.read(_command())

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_reader_error_message_is_stable_and_generic() -> None:
    reader, _ = _reader(FakeRepository(snapshots=()))

    with pytest.raises(PortfolioSnapshotReadError) as raised:
        await reader.read(_command(required_snapshot_id="secret-snapshot"))

    assert str(raised.value) == (
        "Persisted AccountSnapshot evidence cannot produce a complete portfolio view."
    )
    assert "secret" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        cast(Any, object()),
        _command(account_id=""),
        _command(account_id=" account-1"),
        _command(required_snapshot_id=""),
        _command(required_snapshot_id=" snapshot-1"),
        _command(currency="EU"),
        _command(currency="eur"),
        _command(timestamp=datetime(2032, 8, 2, tzinfo=UTC)),
        _command(timestamp=datetime(2032, 8, 2, 0, 0, 0, 1)),
        _command(timestamp=datetime(2032, 8, 2, 0, 1)),
        _command(granularity=cast(Any, "day")),
        _command(calculation_version=0),
        _command(calculation_version=cast(Any, True)),
        _command(calculation_version=2_147_483_648),
    ],
)
async def test_invalid_command_fails_before_repository_access(command: object) -> None:
    repository = FakeRepository()
    reader, _ = _reader(repository)

    with pytest.raises(PortfolioSnapshotReadError):
        await reader.read(cast(Any, command))

    assert repository.isolation_calls == 0


def _invalid_repository(case: str) -> FakeRepository:
    account = _account()
    snapshot = _snapshot()
    items = list(_items())
    if case == "missing account":
        repository = FakeRepository()
        repository.account = None
        return repository
    if case == "wrong account":
        account.id = "account-other"
    elif case == "unsupported account":
        account.type = DbAccountType.bank
    elif case == "account currency":
        account.currency = "eur"
    elif case == "archive missing timestamp":
        account.is_archived = True
    elif case == "archive unexpected timestamp":
        account.archived_at = SNAPSHOT_AT
    elif case == "missing snapshot":
        return FakeRepository(account=account, snapshots=(), items=tuple(items))
    elif case == "multiple snapshots":
        return FakeRepository(
            account=account,
            snapshots=(snapshot, _snapshot(snapshot_id="snapshot-2")),
            items=tuple(items),
        )
    elif case == "snapshot account":
        snapshot.account_id = "account-other"
    elif case == "snapshot timestamp":
        snapshot.timestamp = datetime(2032, 8, 3)
    elif case == "snapshot granularity":
        snapshot.granularity = DbSnapshotGranularity.hour
    elif case == "snapshot currency":
        snapshot.currency = "USD"
    elif case == "snapshot version":
        snapshot.calculation_version = 2
    elif case == "snapshot source":
        snapshot.source = cast(Any, "manual_recalculation")
    elif case == "recalculated":
        snapshot.is_recalculated = False
    elif case == "decimal":
        snapshot.total_value = cast(Any, 110.0)
    elif case == "snapshot timestamp scale":
        snapshot.created_at = datetime(2032, 8, 2, 0, 0, 0, 1)
    elif case == "item snapshot":
        items[0].item.snapshot_id = "snapshot-other"
    elif case == "null asset id":
        items[0].item.asset_id = None
    elif case == "missing listing":
        items[0] = replace(items[0], listing=None)
    elif case == "missing asset":
        items[0] = replace(items[0], asset=None)
    elif case == "listing id":
        assert items[0].listing is not None
        items[0].listing.id = "listing-other"
    elif case == "listing asset":
        assert items[0].listing is not None
        items[0].listing.asset_id = "asset-other"
    elif case == "item asset":
        items[0].item.asset_id = "asset-other"
    elif case == "symbol":
        items[0].item.symbol = "OTHER"
    elif case == "asset name":
        assert items[0].asset is not None
        items[0].asset.name = None
    elif case == "price currency":
        items[0].item.price_currency = None
    elif case == "price source":
        items[0].item.price_source = None
    elif case == "future price":
        items[0].item.price_timestamp = datetime(2032, 8, 3)
    elif case == "value currency":
        items[0].item.value_currency = "JPY"
    elif case == "listing currency":
        assert items[0].listing is not None
        items[0].listing.currency = "JPY"
    elif case == "cost currency":
        items[0].item.cost_currency = "CZK"
    elif case == "native value":
        items[0].item.native_value = None
    elif case == "cost basis":
        items[0].item.cost_basis = None
    elif case == "native cost":
        items[0].item.native_cost_basis = None
    elif case == "native cost currency":
        items[0].item.native_cost_currency = None
    elif case == "item created timestamp":
        items[0].item.created_at = SNAPSHOT_AT
    elif case == "duplicate item":
        items[1].item.id = items[0].item.id
    elif case == "duplicate listing":
        items[1].item.listing_id = items[0].item.listing_id
        assert items[1].listing is not None and items[0].listing is not None
        items[1].listing.id = items[0].listing.id
    elif case == "allocation":
        items[0].item.allocation_pct = Decimal("60.00001")
    elif case == "item sums":
        items[0].item.value = Decimal("59")
    elif case == "unrealized scale":
        items[0].item.cost_basis = Decimal("50.00000000001")
    else:
        raise AssertionError(case)
    return FakeRepository(account=account, snapshots=(snapshot,), items=tuple(items))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing account",
        "wrong account",
        "unsupported account",
        "account currency",
        "archive missing timestamp",
        "archive unexpected timestamp",
        "missing snapshot",
        "multiple snapshots",
        "snapshot account",
        "snapshot timestamp",
        "snapshot granularity",
        "snapshot currency",
        "snapshot version",
        "snapshot source",
        "recalculated",
        "decimal",
        "snapshot timestamp scale",
        "item snapshot",
        "null asset id",
        "missing listing",
        "missing asset",
        "listing id",
        "listing asset",
        "item asset",
        "symbol",
        "asset name",
        "price currency",
        "price source",
        "future price",
        "value currency",
        "listing currency",
        "cost currency",
        "native value",
        "cost basis",
        "native cost",
        "native cost currency",
        "item created timestamp",
        "duplicate item",
        "duplicate listing",
        "allocation",
        "item sums",
        "unrealized scale",
    ],
)
async def test_corrupt_persisted_evidence_fails_closed(case: str) -> None:
    reader, _ = _reader(_invalid_repository(case))

    with pytest.raises(
        PortfolioSnapshotReadError,
        match=(r"^Persisted AccountSnapshot evidence cannot produce a complete portfolio view\.$"),
    ):
        await reader.read(_command())


def test_reader_boundary_excludes_live_financial_dependencies_and_side_effects() -> None:
    paths = (MODULE_DIR / "reader.py", MODULE_DIR / "repository.py")
    forbidden_imported_names = {
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "InvestmentEventModel",
        "InvestmentMovementModel",
        "TransactionModel",
        "NetWorthSnapshotModel",
        "UserModel",
        "AccountMemberModel",
        "ImportBatchModel",
        "ImportRowModel",
    }
    forbidden_calls = {"float", "round", "uuid4"}
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not forbidden_imported_names.intersection(imported_names)
        assert "app.modules.portfolio.repository" not in source
        assert ".commit(" not in source
        assert ".rollback(" not in source
        assert "with_for_update" not in source
        assert ".limit(" not in source
        assert "timestamp.desc" not in source
        assert "FOR UPDATE" not in source
        assert "advisory" not in source.lower()
        assert not any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id in forbidden_calls)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in {"now", "uuid4"})
            )
            for node in ast.walk(tree)
        )
