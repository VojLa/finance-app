"""Pure deterministic projection of an exact multi-account portfolio snapshot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.modules.dashboard_snapshot.models import (
    DashboardAccountCard,
    DashboardAssetTypeAllocation,
    DashboardSnapshotSummary,
    DashboardSnapshotView,
    DashboardTopPosition,
)
from app.modules.portfolio_snapshot.aggregate_models import (
    MultiAccountPortfolioAccountView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSummaryView,
    SnapshotGranularity,
)

_ERROR_MESSAGE = "Portfolio snapshot evidence cannot produce a complete dashboard view."
_MONEY = (18, 6)
_QUANTITY = (28, 10)
_PERCENTAGE = (8, 4)
_POSTGRES_INTEGER_MAX = 2_147_483_647
_INVESTMENT_ACCOUNT_TYPES = frozenset(
    (AccountType.broker, AccountType.exchange, AccountType.crypto_wallet)
)
_LIABILITY_ACCOUNT_TYPES = frozenset(
    (AccountType.credit_card, AccountType.loan, AccountType.mortgage)
)


class DashboardSnapshotProjectionError(ValueError):
    """Raised when portfolio evidence cannot form one complete dashboard view."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


def _fail() -> DashboardSnapshotProjectionError:
    return DashboardSnapshotProjectionError()


def _text(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _text(value)
    if len(currency) != 3 or any(character < "A" or character > "Z" for character in currency):
        raise _fail()
    return currency


def _count(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > _POSTGRES_INTEGER_MAX:
        raise _fail()
    return value


def _timestamp(value: object, granularity: SnapshotGranularity) -> datetime:
    if type(value) is not datetime or value.tzinfo is not None or value.microsecond % 1_000 != 0:
        raise _fail()
    if granularity is SnapshotGranularity.minute:
        aligned = value.second == 0 and value.microsecond == 0
    elif granularity is SnapshotGranularity.hour:
        aligned = value.minute == 0 and value.second == 0 and value.microsecond == 0
    elif granularity is SnapshotGranularity.day:
        aligned = value.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.week:
        aligned = value.weekday() == 0 and value.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.month:
        aligned = value.day == 1 and value.time() == datetime.min.time()
    else:
        raise _fail()
    if not aligned:
        raise _fail()
    return value


def _exact(
    value: object,
    numeric: tuple[int, int],
    *,
    nonnegative: bool = False,
) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise _fail()
    precision, scale = numeric
    try:
        with localcontext() as context:
            context.prec = 112
            scaled = value.quantize(Decimal(1).scaleb(-scale))
            limit = Decimal(10) ** (precision - scale)
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or value.copy_abs() >= limit or (nonnegative and value < 0):
        raise _fail()
    return value


def _sum(values: tuple[Decimal, ...], numeric: tuple[int, int]) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = sum(values, Decimal(0))
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact(result, numeric)


def _add(left: Decimal, right: Decimal, numeric: tuple[int, int]) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = left + right
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact(result, numeric)


def _subtract(left: Decimal, right: Decimal, numeric: tuple[int, int]) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = left - right
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact(result, numeric)


def _percentage(value: Decimal, total: Decimal) -> Decimal:
    if value < 0 or total <= 0:
        raise _fail()
    try:
        with localcontext() as context:
            context.prec = 112
            result = value / total * Decimal(100)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        raise _fail() from exc
    return _exact(result, _PERCENTAGE, nonnegative=True)


def _validate_summary(summary: object) -> MultiAccountPortfolioSummary:
    if type(summary) is not MultiAccountPortfolioSummary:
        raise _fail()
    cash = _exact(summary.cash_value, _MONEY)
    investment = _exact(summary.investment_value, _MONEY, nonnegative=True)
    _exact(summary.investment_cost_basis, _MONEY, nonnegative=True)
    liabilities = _exact(summary.liabilities_value, _MONEY, nonnegative=True)
    total = _exact(summary.total_value, _MONEY)
    _exact(summary.unrealized_pnl_value, _MONEY)
    _exact(summary.net_deposits_value, _MONEY)
    _exact(summary.realized_pnl_value, _MONEY)
    _exact(summary.fees_value, _MONEY, nonnegative=True)
    _exact(summary.taxes_value, _MONEY, nonnegative=True)
    _count(summary.account_count, positive=True)
    _count(summary.position_count)
    assets = _add(cash, investment, _MONEY)
    if _subtract(assets, liabilities, _MONEY) != total:
        raise _fail()
    return summary


def _validate_position(
    position: object,
    *,
    output_currency: str,
) -> PortfolioPositionView:
    if type(position) is not PortfolioPositionView:
        raise _fail()
    _text(position.listing_id)
    _text(position.asset_id)
    _text(position.symbol)
    _text(position.name)
    if type(position.asset_type) is not AssetType:
        raise _fail()
    _exact(position.value, _MONEY, nonnegative=True)
    _exact(position.unrealized_pnl, _QUANTITY)
    if (
        _currency(position.value_currency) != output_currency
        or _currency(position.cost_currency) != output_currency
    ):
        raise _fail()
    return position


def _account_card(
    account_view: object,
    *,
    output_currency: str,
    account_ids: set[str],
    snapshot_ids: set[str],
) -> tuple[DashboardAccountCard, tuple[tuple[str, PortfolioPositionView], ...], bool]:
    if (
        type(account_view) is not MultiAccountPortfolioAccountView
        or type(account_view.account) is not PortfolioAccountView
        or type(account_view.summary) is not PortfolioSummaryView
        or type(account_view.positions) is not tuple
    ):
        raise _fail()
    account_id = _text(account_view.account.account_id)
    snapshot_id = _text(account_view.snapshot_id)
    if account_id in account_ids or snapshot_id in snapshot_ids:
        raise _fail()
    account_ids.add(account_id)
    snapshot_ids.add(snapshot_id)
    name = _text(account_view.account.name)
    if type(account_view.account.account_type) is not AccountType:
        raise _fail()
    account_type = account_view.account.account_type
    is_investment = account_type in _INVESTMENT_ACCOUNT_TYPES
    if not is_investment and account_type not in _LIABILITY_ACCOUNT_TYPES:
        raise _fail()
    account_currency = _currency(account_view.account.currency)
    summary = account_view.summary
    cash = _exact(summary.cash_value, _MONEY)
    investment = _exact(summary.investment_value, _MONEY, nonnegative=True)
    _exact(summary.investment_cost_basis, _MONEY, nonnegative=True)
    liabilities = _exact(summary.liabilities_value, _MONEY, nonnegative=True)
    total = _exact(summary.total_value, _MONEY)
    _exact(summary.net_deposits_value, _MONEY)
    _exact(summary.realized_pnl_value, _MONEY)
    unrealized = _exact(summary.unrealized_pnl_value, _MONEY)
    _exact(summary.fees_value, _MONEY, nonnegative=True)
    _exact(summary.taxes_value, _MONEY, nonnegative=True)
    if _count(summary.position_count) != len(account_view.positions):
        raise _fail()
    scoped_positions = tuple(
        (
            account_id,
            _validate_position(position, output_currency=output_currency),
        )
        for position in account_view.positions
    )
    if not is_investment and scoped_positions:
        raise _fail()
    return (
        DashboardAccountCard(
            account_id=account_id,
            snapshot_id=snapshot_id,
            name=name,
            account_type=account_type,
            account_currency=account_currency,
            output_currency=output_currency,
            total_value=total,
            cash_value=cash,
            investment_value=investment,
            liabilities_value=liabilities,
            unrealized_pnl_value=unrealized,
            position_count=len(scoped_positions),
        ),
        scoped_positions,
        is_investment,
    )


def _allocations(
    positions: tuple[tuple[str, PortfolioPositionView], ...],
    investment_value: Decimal,
) -> tuple[DashboardAssetTypeAllocation, ...]:
    if investment_value == 0:
        return ()
    grouped: dict[AssetType, tuple[Decimal, int, set[str]]] = {}
    for account_id, position in positions:
        existing = grouped.get(position.asset_type)
        if existing is None:
            grouped[position.asset_type] = (position.value, 1, {account_id})
        else:
            grouped[position.asset_type] = (
                _add(existing[0], position.value, _MONEY),
                existing[1] + 1,
                existing[2] | {account_id},
            )
    allocations = tuple(
        DashboardAssetTypeAllocation(
            asset_type=asset_type,
            value=value,
            allocation_pct=_percentage(value, investment_value),
            position_count=position_count,
            account_count=len(account_ids),
        )
        for asset_type, (value, position_count, account_ids) in grouped.items()
    )
    ordered = tuple(
        sorted(
            allocations,
            key=lambda allocation: (
                allocation.value.copy_negate(),
                allocation.asset_type.value,
            ),
        )
    )
    if _sum(tuple(item.value for item in ordered), _MONEY) != investment_value or _sum(
        tuple(item.allocation_pct for item in ordered), _PERCENTAGE
    ) != Decimal("100.0000"):
        raise _fail()
    return ordered


def _top_positions(
    positions: tuple[tuple[str, PortfolioPositionView], ...],
    investment_value: Decimal,
) -> tuple[DashboardTopPosition, ...]:
    if investment_value == 0:
        return ()
    projected = tuple(
        DashboardTopPosition(
            account_id=account_id,
            listing_id=position.listing_id,
            asset_id=position.asset_id,
            symbol=position.symbol,
            name=position.name,
            asset_type=position.asset_type,
            value=position.value,
            value_currency=position.value_currency,
            unrealized_pnl=position.unrealized_pnl,
            allocation_pct=_percentage(position.value, investment_value),
        )
        for account_id, position in positions
    )
    ordered = tuple(
        sorted(
            projected,
            key=lambda position: (
                position.value.copy_negate(),
                position.unrealized_pnl.copy_negate(),
                position.asset_type.value,
                position.symbol,
                position.account_id,
                position.listing_id,
                position.asset_id,
            ),
        )
    )
    if _sum(tuple(item.value for item in ordered), _MONEY) != investment_value or _sum(
        tuple(item.allocation_pct for item in ordered), _PERCENTAGE
    ) != Decimal("100.0000"):
        raise _fail()
    return ordered


def build_dashboard_snapshot_view(portfolio: MultiAccountPortfolioView) -> DashboardSnapshotView:
    """Project one coherent 5L-D portfolio into immutable dashboard values."""

    try:
        if (
            type(portfolio) is not MultiAccountPortfolioView
            or type(portfolio.accounts) is not tuple
            or not portfolio.accounts
            or type(portfolio.granularity) is not SnapshotGranularity
        ):
            raise _fail()
        granularity = portfolio.granularity
        timestamp = _timestamp(portfolio.timestamp, granularity)
        currency = _currency(portfolio.currency)
        calculation_version = _count(portfolio.calculation_version, positive=True)
        summary = _validate_summary(portfolio.summary)
        account_ids: set[str] = set()
        snapshot_ids: set[str] = set()
        cards: list[DashboardAccountCard] = []
        positions: list[tuple[str, PortfolioPositionView]] = []
        investment_account_count = 0
        for account_view in portfolio.accounts:
            card, scoped_positions, is_investment = _account_card(
                account_view,
                output_currency=currency,
                account_ids=account_ids,
                snapshot_ids=snapshot_ids,
            )
            cards.append(card)
            positions.extend(scoped_positions)
            investment_account_count += int(is_investment)
        if summary.account_count != len(cards) or summary.position_count != len(positions):
            raise _fail()
        scoped = tuple(positions)
        if (
            _sum(tuple(position.value for _, position in scoped), _MONEY)
            != summary.investment_value
        ):
            raise _fail()
        assets_value = _add(summary.cash_value, summary.investment_value, _MONEY)
        dashboard_summary = DashboardSnapshotSummary(
            total_value=summary.total_value,
            assets_value=assets_value,
            liabilities_value=summary.liabilities_value,
            cash_value=summary.cash_value,
            investment_value=summary.investment_value,
            investment_cost_basis=summary.investment_cost_basis,
            unrealized_pnl_value=summary.unrealized_pnl_value,
            realized_pnl_value=summary.realized_pnl_value,
            net_deposits_value=summary.net_deposits_value,
            fees_value=summary.fees_value,
            taxes_value=summary.taxes_value,
            account_count=summary.account_count,
            investment_account_count=investment_account_count,
            liability_account_count=len(cards) - investment_account_count,
            position_count=summary.position_count,
        )
        return DashboardSnapshotView(
            timestamp=timestamp,
            granularity=granularity,
            currency=currency,
            calculation_version=calculation_version,
            summary=dashboard_summary,
            accounts=tuple(
                sorted(
                    cards,
                    key=lambda card: (
                        card.account_type.value,
                        card.name,
                        card.account_id,
                        card.snapshot_id,
                    ),
                )
            ),
            asset_type_allocations=_allocations(scoped, summary.investment_value),
            top_positions=_top_positions(scoped, summary.investment_value),
        )
    except DashboardSnapshotProjectionError:
        raise
    except (AttributeError, InvalidOperation, OverflowError, TypeError, ValueError) as exc:
        raise _fail() from exc
