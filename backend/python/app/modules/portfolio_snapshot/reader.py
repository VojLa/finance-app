"""Read one exact persisted AccountSnapshot into the pure portfolio view."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Numeric, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.common import MONEY, PERCENTAGE, QUANTITY, TIMESTAMP
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
    decode_portfolio_currency_breakdown,
    decode_portfolio_quantity_breakdown,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    PortfolioSnapshotView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.projection import (
    PortfolioSnapshotProjectionError,
    build_portfolio_snapshot_view,
)
from app.modules.portfolio_snapshot.repository import (
    PersistedPortfolioSnapshotItem,
    PortfolioSnapshotRepository,
)
from app.modules.portfolio_snapshot.writer import valuation_evidence_timestamp

_ERROR_MESSAGE = "Persisted AccountSnapshot evidence cannot produce a complete portfolio view."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_COHERENT_ISOLATION_LEVELS = {"repeatable read", "serializable"}
_ACCOUNT_TYPE_MAP = {
    DbAccountType.bank: AccountType.bank,
    DbAccountType.cash: AccountType.cash,
    DbAccountType.savings: AccountType.savings,
    DbAccountType.broker: AccountType.broker,
    DbAccountType.exchange: AccountType.exchange,
    DbAccountType.crypto_wallet: AccountType.crypto_wallet,
    DbAccountType.credit_card: AccountType.credit_card,
    DbAccountType.loan: AccountType.loan,
    DbAccountType.mortgage: AccountType.mortgage,
}
_ASSET_TYPE_MAP = {
    DbAssetType.stock: AssetType.stock,
    DbAssetType.etf: AssetType.etf,
    DbAssetType.crypto: AssetType.crypto,
    DbAssetType.commodity: AssetType.commodity,
    DbAssetType.cash: AssetType.cash,
    DbAssetType.bond: AssetType.bond,
    DbAssetType.other: AssetType.other,
}
_GRANULARITY_TO_DB = {
    SnapshotGranularity.minute: DbSnapshotGranularity.minute,
    SnapshotGranularity.hour: DbSnapshotGranularity.hour,
    SnapshotGranularity.day: DbSnapshotGranularity.day,
    SnapshotGranularity.week: DbSnapshotGranularity.week,
    SnapshotGranularity.month: DbSnapshotGranularity.month,
}
_GRANULARITY_FROM_DB = {database: pure for pure, database in _GRANULARITY_TO_DB.items()}
_SOURCE_MAP = {
    DbSnapshotSource.import_event: SnapshotSource.import_event,
    DbSnapshotSource.price_refresh: SnapshotSource.price_refresh,
    DbSnapshotSource.holdings_recalculation: SnapshotSource.holdings_recalculation,
    DbSnapshotSource.scheduled: SnapshotSource.scheduled,
    DbSnapshotSource.manual_recalculation: SnapshotSource.manual_recalculation,
}


class PortfolioSnapshotReadError(ValueError):
    """Raised when persisted evidence cannot build the exact portfolio view."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class ReadExactPortfolioSnapshotCommand:
    """Exact immutable physical identity requested by an internal caller."""

    account_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    required_snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class CompletePortfolioSnapshotRead:
    """Pure view plus internal deterministic persistence lineage."""

    view: PortfolioSnapshotView
    selected_snapshot_id: str
    selected_item_ids: tuple[str, ...]
    valuation_timestamp: datetime | None = None


class PreloadedPortfolioSnapshotRepository(PortfolioSnapshotRepository):
    """Set-based evidence load for a single caller-owned repeatable-read view."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        isolation: str | None,
        accounts: tuple[AccountModel, ...],
        snapshots: tuple[AccountSnapshotModel, ...],
        items: tuple[PersistedPortfolioSnapshotItem, ...],
    ) -> None:
        super().__init__(session)
        self.isolation = isolation
        self.accounts = {account.id: account for account in accounts}
        self.snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
        self.snapshots: dict[
            tuple[str, datetime, DbSnapshotGranularity, str], list[AccountSnapshotModel]
        ] = {}
        for snapshot in snapshots:
            self.snapshots.setdefault(
                (snapshot.account_id, snapshot.timestamp, snapshot.granularity, snapshot.currency),
                [],
            ).append(snapshot)
        self.items: dict[str, list[PersistedPortfolioSnapshotItem]] = {}
        for item in items:
            self.items.setdefault(item.item.snapshot_id, []).append(item)

    @classmethod
    async def load(
        cls,
        session: AsyncSession,
        *,
        account_ids: tuple[str, ...],
        timestamp: datetime,
        granularity: DbSnapshotGranularity,
        currencies: tuple[str, ...],
    ) -> PreloadedPortfolioSnapshotRepository:
        isolation = await PortfolioSnapshotRepository(session).load_transaction_isolation()
        accounts = tuple(
            (
                await session.scalars(
                    select(AccountModel)
                    .where(AccountModel.id.in_(account_ids))
                    .execution_options(autoflush=False, populate_existing=True)
                )
            ).all()
        )
        snapshots = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(
                        AccountSnapshotModel.account_id.in_(account_ids),
                        AccountSnapshotModel.timestamp == timestamp,
                        AccountSnapshotModel.granularity == granularity,
                        AccountSnapshotModel.currency.in_(currencies),
                    )
                    .execution_options(autoflush=False, populate_existing=True)
                )
            ).all()
        )
        snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
        items: tuple[PersistedPortfolioSnapshotItem, ...] = ()
        if snapshot_ids:
            rows = (
                await session.execute(
                    select(AccountSnapshotItemModel, AssetListingModel, AssetModel)
                    .outerjoin(
                        AssetListingModel,
                        AssetListingModel.id == AccountSnapshotItemModel.listing_id,
                    )
                    .outerjoin(AssetModel, AssetModel.id == AssetListingModel.asset_id)
                    .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                    .execution_options(autoflush=False, populate_existing=True)
                )
            ).all()
            items = tuple(
                PersistedPortfolioSnapshotItem(item, listing, asset)
                for item, listing, asset in rows
            )
        return cls(
            session, isolation=isolation, accounts=accounts, snapshots=snapshots, items=items
        )

    async def load_transaction_isolation(self) -> str | None:
        return self.isolation

    async def load_account(self, account_id: str) -> AccountModel | None:
        return self.accounts.get(account_id)

    async def load_exact_snapshots(
        self,
        *,
        account_id: str,
        timestamp: datetime,
        granularity: DbSnapshotGranularity,
        currency: str,
        required_snapshot_id: str | None = None,
    ) -> tuple[AccountSnapshotModel, ...]:
        snapshots = tuple(self.snapshots.get((account_id, timestamp, granularity, currency), ()))
        if required_snapshot_id is None:
            return snapshots
        return tuple(snapshot for snapshot in snapshots if snapshot.id == required_snapshot_id)

    async def load_snapshot_items(
        self, snapshot_id: str
    ) -> tuple[PersistedPortfolioSnapshotItem, ...]:
        return tuple(self.items.get(snapshot_id, ()))

    def resolve_generation_peer_snapshot_id(
        self,
        *,
        primary_snapshot_id: str,
        account_id: str,
        timestamp: datetime,
        granularity: DbSnapshotGranularity,
        currency: str,
    ) -> str | None:
        """Resolve one presentation projection from the primary's immutable generation."""

        primary = self.snapshots_by_id.get(primary_snapshot_id)
        if primary is None:
            return None
        candidates = tuple(
            snapshot
            for snapshot in self.snapshots.get((account_id, timestamp, granularity, currency), ())
            if snapshot.generation_id == primary.generation_id
        )
        if len(candidates) != 1:
            return None
        return candidates[0].id


type ProjectionBuilder = Callable[[PortfolioSnapshotSource], PortfolioSnapshotView]


def _fail() -> PortfolioSnapshotReadError:
    return PortfolioSnapshotReadError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or any(character < "A" or character > "Z" for character in result):
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _aligned_timestamp(value: object, granularity: SnapshotGranularity) -> datetime:
    timestamp = _timestamp(value)
    if granularity is SnapshotGranularity.minute:
        aligned = timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.hour:
        aligned = timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.day:
        aligned = timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.week:
        aligned = timestamp.weekday() == 0 and timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.month:
        aligned = timestamp.day == 1 and timestamp.time() == datetime.min.time()
    else:
        raise _fail()
    if not aligned:
        raise _fail()
    return timestamp


def _calculation_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _exact(
    value: object,
    numeric: Numeric,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric types must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (nonnegative and value < 0)
        or (positive and value <= 0)
    ):
        raise _fail()
    return value


def _subtract(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = left - right
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact(result, QUANTITY)


def _validate_command(command: object) -> ReadExactPortfolioSnapshotCommand:
    if not isinstance(command, ReadExactPortfolioSnapshotCommand):
        raise _fail()
    account_id = _nonblank(command.account_id)
    if not isinstance(command.granularity, SnapshotGranularity):
        raise _fail()
    timestamp = _aligned_timestamp(command.timestamp, command.granularity)
    currency = _currency(command.currency)
    calculation_version = _calculation_version(command.calculation_version)
    required_snapshot_id = (
        None if command.required_snapshot_id is None else _nonblank(command.required_snapshot_id)
    )
    return ReadExactPortfolioSnapshotCommand(
        account_id=account_id,
        timestamp=timestamp,
        granularity=command.granularity,
        currency=currency,
        calculation_version=calculation_version,
        required_snapshot_id=required_snapshot_id,
    )


def _account(
    source: object, command: ReadExactPortfolioSnapshotCommand
) -> tuple[AccountModel, AccountType]:
    if not isinstance(source, AccountModel):
        raise _fail()
    if (
        _nonblank(source.id) != command.account_id
        or not isinstance(source.type, DbAccountType)
        or source.type not in _ACCOUNT_TYPE_MAP
        or not isinstance(source.is_archived, bool)
    ):
        raise _fail()
    _nonblank(source.name)
    _currency(source.currency)
    if source.is_archived:
        if source.archived_at is None:
            raise _fail()
        _timestamp(source.archived_at)
    elif source.archived_at is not None:
        raise _fail()
    return source, _ACCOUNT_TYPE_MAP[source.type]


def _snapshot(
    source: object,
    *,
    account: AccountModel,
    command: ReadExactPortfolioSnapshotCommand,
) -> tuple[AccountSnapshotModel, SnapshotGranularity, SnapshotSource]:
    if not isinstance(source, AccountSnapshotModel):
        raise _fail()
    snapshot_id = _nonblank(source.id)
    if (
        _nonblank(source.account_id) != account.id
        or _timestamp(source.timestamp) != command.timestamp
        or not isinstance(source.granularity, DbSnapshotGranularity)
        or source.granularity not in _GRANULARITY_FROM_DB
        or _GRANULARITY_FROM_DB[source.granularity] is not command.granularity
        or _currency(source.currency) != command.currency
        or not isinstance(source.source, DbSnapshotSource)
        or source.source not in _SOURCE_MAP
        or not isinstance(source.is_recalculated, bool)
        or source.is_recalculated is not (source.source is DbSnapshotSource.manual_recalculation)
        or _calculation_version(source.calculation_version) != command.calculation_version
        or (
            command.required_snapshot_id is not None and snapshot_id != command.required_snapshot_id
        )
    ):
        raise _fail()
    _timestamp(source.calculated_at)
    _timestamp(source.created_at)
    _exact(source.cash_value, MONEY)
    _exact(source.investment_value, MONEY, nonnegative=True)
    if source.investment_cost_basis is not None:
        _exact(source.investment_cost_basis, MONEY, nonnegative=True)
    _exact(source.liabilities_value, MONEY, nonnegative=True)
    _exact(source.total_value, MONEY)
    if source.net_deposits_value is not None:
        _exact(source.net_deposits_value, MONEY)
    if source.realized_pnl_value is not None:
        _exact(source.realized_pnl_value, MONEY)
    if source.unrealized_pnl_value is not None:
        _exact(source.unrealized_pnl_value, MONEY)
    _exact(source.fees_value, MONEY, nonnegative=True)
    _exact(source.taxes_value, MONEY, nonnegative=True)
    return source, _GRANULARITY_FROM_DB[source.granularity], _SOURCE_MAP[source.source]


def _item(
    source: object,
    *,
    snapshot: AccountSnapshotModel,
) -> tuple[str, str, str, PortfolioSnapshotItemSource]:
    if not isinstance(source, PersistedPortfolioSnapshotItem):
        raise _fail()
    item = source.item
    listing = source.listing
    asset = source.asset
    if (
        not isinstance(item, AccountSnapshotItemModel)
        or not isinstance(listing, AssetListingModel)
        or not isinstance(asset, AssetModel)
    ):
        raise _fail()
    item_id = _nonblank(item.id)
    listing_id = _nonblank(item.listing_id)
    asset_id = _nonblank(item.asset_id)
    if (
        _nonblank(item.snapshot_id) != snapshot.id
        or listing_id != _nonblank(listing.id)
        or _nonblank(listing.asset_id) != _nonblank(asset.id)
        or asset_id != asset.id
        or _nonblank(item.symbol) != _nonblank(listing.symbol)
        or not isinstance(asset.asset_type, DbAssetType)
        or asset.asset_type not in _ASSET_TYPE_MAP
        or not isinstance(item.price_source, PriceSource)
    ):
        raise _fail()
    asset_name = _nonblank(asset.name)
    _currency(listing.currency)
    price_currency = _currency(item.price_currency)
    physical_value_currency = _currency(item.value_currency)
    # Listing currency remains acquisition metadata. Persisted price/value
    # evidence owns its explicit provider quote currency.
    if price_currency != physical_value_currency:
        raise _fail()
    quantity = _exact(item.quantity, QUANTITY, positive=True)
    price_per_unit = _exact(item.price_per_unit, QUANTITY, positive=True)
    price_timestamp = _timestamp(item.price_timestamp)
    value = _exact(item.value, MONEY, positive=True)
    cost_values = (
        item.cost_basis,
        item.cost_currency,
        item.native_cost_basis,
        item.native_cost_currency,
        item.native_cost_basis_by_currency,
        item.average_buy_price,
        item.average_buy_price_currency,
    )
    cost_complete = all(value is not None for value in cost_values)
    if not cost_complete and any(value is not None for value in cost_values):
        raise _fail()
    cost_basis = (
        None if item.cost_basis is None else _exact(item.cost_basis, QUANTITY, positive=True)
    )
    cost_currency = None if item.cost_currency is None else _currency(item.cost_currency)
    allocation_pct = _exact(item.allocation_pct, PERCENTAGE, positive=True)
    created_at = _timestamp(item.created_at)
    native_value = _exact(item.native_value, QUANTITY, positive=True)
    native_cost_basis = (
        None
        if item.native_cost_basis is None
        else _exact(item.native_cost_basis, QUANTITY, positive=True)
    )
    native_cost_currency = (
        None if item.native_cost_currency is None else _currency(item.native_cost_currency)
    )
    average_buy_price = (
        None
        if item.average_buy_price is None
        else _exact(item.average_buy_price, QUANTITY, positive=True)
    )
    average_buy_price_currency = (
        None
        if item.average_buy_price_currency is None
        else _currency(item.average_buy_price_currency)
    )
    if cost_complete and cost_currency != snapshot.currency:
        raise _fail()
    native_cost_basis_by_currency = (
        None
        if item.native_cost_basis_by_currency is None
        else decode_portfolio_quantity_breakdown(item.native_cost_basis_by_currency)
    )
    if (
        cost_complete
        and native_cost_basis_by_currency is not None
        and len(native_cost_basis_by_currency) == 1
    ):
        component = native_cost_basis_by_currency[0]
        if native_cost_basis != component.amount or native_cost_currency != component.currency:
            raise _fail()
    elif cost_complete and (
        native_cost_basis_by_currency is None
        or native_cost_basis != cost_basis
        or native_cost_currency != cost_currency
    ):
        raise _fail()
    if price_timestamp > snapshot.timestamp or created_at != snapshot.created_at:
        raise _fail()
    return (
        item_id,
        listing_id,
        asset_id,
        PortfolioSnapshotItemSource(
            item_id=item_id,
            listing_id=listing_id,
            asset_id=asset_id,
            symbol=item.symbol,
            name=asset_name,
            asset_type=_ASSET_TYPE_MAP[asset.asset_type],
            quantity=quantity,
            price_per_unit=price_per_unit,
            price_currency=price_currency,
            price_timestamp=price_timestamp,
            value=value,
            value_currency=snapshot.currency,
            cost_basis=cost_basis,
            cost_currency=cost_currency,
            unrealized_pnl=(None if cost_basis is None else _subtract(value, cost_basis)),
            allocation_pct=allocation_pct,
            native_value=native_value,
            native_value_currency=physical_value_currency,
            native_cost_basis=native_cost_basis,
            native_cost_currency=native_cost_currency,
            native_cost_basis_by_currency=native_cost_basis_by_currency,
            average_buy_price=average_buy_price,
            average_buy_price_currency=average_buy_price_currency,
        ),
    )


def _items(
    sources: object,
    *,
    snapshot: AccountSnapshotModel,
) -> tuple[tuple[PortfolioSnapshotItemSource, ...], tuple[str, ...]]:
    if not isinstance(sources, tuple):
        raise _fail()
    mapped: list[tuple[str, str, str, PortfolioSnapshotItemSource]] = []
    item_ids: set[str] = set()
    listing_ids: set[str] = set()
    asset_listing_ids: set[tuple[str, str]] = set()
    for source in sources:
        item_id, listing_id, asset_id, pure = _item(source, snapshot=snapshot)
        asset_listing_id = (asset_id, listing_id)
        if (
            item_id in item_ids
            or listing_id in listing_ids
            or asset_listing_id in asset_listing_ids
        ):
            raise _fail()
        item_ids.add(item_id)
        listing_ids.add(listing_id)
        asset_listing_ids.add(asset_listing_id)
        mapped.append((item_id, listing_id, asset_id, pure))
    ordered = tuple(sorted(mapped, key=lambda value: (value[1], value[0], value[2])))
    return tuple(value[3] for value in ordered), tuple(sorted(item_ids))


class PortfolioSnapshotReader:
    """Build an exact immutable portfolio view inside a coherent caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: PortfolioSnapshotRepository | None = None,
        projection_builder: ProjectionBuilder = build_portfolio_snapshot_view,
    ) -> None:
        self.session = session
        self.repository = repository or PortfolioSnapshotRepository(session)
        self.projection_builder = projection_builder

    async def read(
        self,
        command: ReadExactPortfolioSnapshotCommand,
    ) -> CompletePortfolioSnapshotRead:
        try:
            canonical = _validate_command(command)
            if self.session.in_transaction() is not True:
                raise _fail()
            isolation = await self.repository.load_transaction_isolation()
            if (
                not isinstance(isolation, str)
                or isolation.replace("_", " ").lower() not in _COHERENT_ISOLATION_LEVELS
            ):
                raise _fail()
            account, account_type = _account(
                await self.repository.load_account(canonical.account_id),
                canonical,
            )
            snapshots = await self.repository.load_exact_snapshots(
                account_id=canonical.account_id,
                timestamp=canonical.timestamp,
                granularity=_GRANULARITY_TO_DB[canonical.granularity],
                currency=canonical.currency,
                required_snapshot_id=canonical.required_snapshot_id,
            )
            if not isinstance(snapshots, tuple) or len(snapshots) != 1:
                raise _fail()
            snapshot, granularity, source = _snapshot(
                snapshots[0],
                account=account,
                command=canonical,
            )
            cash_by_currency = decode_portfolio_currency_breakdown(
                snapshot.cash_value_by_currency,
                scalar_total=snapshot.cash_value,
                output_currency=snapshot.currency,
            )
            net_deposits_by_currency = (
                None
                if snapshot.net_deposits_value is None
                else decode_portfolio_currency_breakdown(
                    snapshot.net_deposits_by_currency,
                    scalar_total=snapshot.net_deposits_value,
                    output_currency=snapshot.currency,
                )
            )
            if (
                (
                    snapshot.investment_cost_basis is None
                    and snapshot.investment_cost_basis_by_currency is not None
                )
                or (
                    snapshot.net_deposits_value is None
                    and snapshot.net_deposits_by_currency is not None
                )
                or (
                    snapshot.realized_pnl_value is None
                    and snapshot.realized_pnl_by_currency is not None
                )
            ):
                raise _fail()
            items, selected_item_ids = _items(
                await self.repository.load_snapshot_items(snapshot.id),
                snapshot=snapshot,
            )
            pure_source = PortfolioSnapshotSource(
                snapshot_id=snapshot.id,
                account_id=account.id,
                account_name=account.name,
                account_type=account_type,
                account_currency=account.currency,
                output_currency=snapshot.currency,
                timestamp=snapshot.timestamp,
                granularity=granularity,
                source=source,
                calculation_version=snapshot.calculation_version,
                calculated_at=snapshot.calculated_at,
                created_at=snapshot.created_at,
                cash_value=snapshot.cash_value,
                cash_by_currency=cash_by_currency,
                investment_value=snapshot.investment_value,
                investment_cost_basis=snapshot.investment_cost_basis,
                liabilities_value=snapshot.liabilities_value,
                total_value=snapshot.total_value,
                net_deposits_value=snapshot.net_deposits_value,
                net_deposits_by_currency=net_deposits_by_currency,
                realized_pnl_value=snapshot.realized_pnl_value,
                unrealized_pnl_value=snapshot.unrealized_pnl_value,
                fees_value=snapshot.fees_value,
                taxes_value=snapshot.taxes_value,
                items=items,
            )
            view = self.projection_builder(pure_source)
            if not isinstance(view, PortfolioSnapshotView):
                raise _fail()
            return CompletePortfolioSnapshotRead(
                view=view,
                selected_snapshot_id=snapshot.id,
                selected_item_ids=selected_item_ids,
                valuation_timestamp=valuation_evidence_timestamp(
                    tuple(item.price_timestamp for item in items),
                    snapshot.exchange_rates,
                    snapshot.calculated_at,
                ),
            )
        except PortfolioSnapshotReadError:
            raise
        except PortfolioSnapshotProjectionError as exc:
            raise _fail() from exc
        except (InvalidOperation, SQLAlchemyError, TypeError, ValueError) as exc:
            raise _fail() from exc
