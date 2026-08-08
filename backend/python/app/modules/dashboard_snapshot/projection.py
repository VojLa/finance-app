"""Pure deterministic projection of an exact multi-account portfolio snapshot."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext

from app.modules.dashboard_snapshot.models import (
    DashboardAccountCard,
    DashboardAssetTypeAllocation,
    DashboardSnapshotSummary,
    DashboardSnapshotView,
    DashboardTopPosition,
)
from app.modules.portfolio_snapshot.aggregate_models import (
    AccountPortfolioPresentationView,
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
_CASH_ACCOUNT_TYPES = frozenset((AccountType.bank, AccountType.cash, AccountType.savings))
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


def _percentages(values: tuple[Decimal, ...], total: Decimal) -> tuple[Decimal, ...]:
    if not values or total <= 0 or any(value < 0 for value in values):
        raise _fail()
    try:
        with localcontext() as context:
            context.prec = 112
            quantum = Decimal("0.0001")
            exact = tuple(value / total * Decimal(100) for value in values)
            floored = tuple(value.quantize(quantum, rounding=ROUND_FLOOR) for value in exact)
            residual_units = int((Decimal("100.0000") - sum(floored, Decimal(0))) / quantum)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        raise _fail() from exc
    if residual_units < 0 or residual_units > len(values):
        raise _fail()
    recipients = {
        index
        for index, _remainder in sorted(
            enumerate(tuple(value - floor for value, floor in zip(exact, floored, strict=True))),
            key=lambda item: (item[1].copy_negate(), item[0]),
        )[:residual_units]
    }
    result = tuple(
        _exact(
            floor + (quantum if index in recipients else Decimal(0)),
            _PERCENTAGE,
            nonnegative=True,
        )
        for index, floor in enumerate(floored)
    )
    if _sum(result, _PERCENTAGE) != Decimal("100.0000"):
        raise _fail()
    return result


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
    primary_snapshot_id: str | None = None,
) -> tuple[
    DashboardAccountCard,
    tuple[tuple[str, PortfolioPositionView], ...],
    bool,
    bool,
]:
    if (
        type(account_view) is not MultiAccountPortfolioAccountView
        or type(account_view.account) is not PortfolioAccountView
        or type(account_view.summary) is not PortfolioSummaryView
        or type(account_view.positions) is not tuple
    ):
        raise _fail()
    account_id = _text(account_view.account.account_id)
    snapshot_id = _text(account_view.snapshot_id)
    primary_snapshot_id = _text(primary_snapshot_id or snapshot_id)
    if account_id in account_ids or snapshot_id in snapshot_ids:
        raise _fail()
    account_ids.add(account_id)
    snapshot_ids.add(snapshot_id)
    name = _text(account_view.account.name)
    if type(account_view.account.account_type) is not AccountType:
        raise _fail()
    account_type = account_view.account.account_type
    is_investment = account_type in _INVESTMENT_ACCOUNT_TYPES
    is_cash = account_type in _CASH_ACCOUNT_TYPES
    is_liability = account_type in _LIABILITY_ACCOUNT_TYPES
    if not is_investment and not is_cash and not is_liability:
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
    if is_cash and (investment != 0 or liabilities != 0):
        raise _fail()
    if is_liability and (cash != 0 or investment != 0):
        raise _fail()
    return (
        DashboardAccountCard(
            account_id=account_id,
            snapshot_id=snapshot_id,
            primary_snapshot_id=primary_snapshot_id,
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
        is_liability,
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
    ordered_groups = tuple(
        sorted(
            grouped.items(),
            key=lambda item: (
                item[1][0].copy_negate(),
                item[0].value,
            ),
        )
    )
    values = tuple(group[1][0] for group in ordered_groups)
    if _sum(values, _MONEY) != investment_value:
        raise _fail()
    percentages = _percentages(values, investment_value)
    return tuple(
        DashboardAssetTypeAllocation(
            asset_type=asset_type,
            value=value,
            allocation_pct=allocation_pct,
            position_count=position_count,
            account_count=len(account_ids),
        )
        for (
            asset_type,
            (value, position_count, account_ids),
        ), allocation_pct in zip(ordered_groups, percentages, strict=True)
    )


def _top_positions(
    positions: tuple[tuple[str, PortfolioPositionView], ...],
    investment_value: Decimal,
) -> tuple[DashboardTopPosition, ...]:
    if investment_value == 0:
        return ()
    ordered_positions = tuple(
        sorted(
            positions,
            key=lambda item: (
                item[1].value.copy_negate(),
                item[1].unrealized_pnl.copy_negate(),
                item[1].asset_type.value,
                item[1].symbol,
                item[0],
                item[1].listing_id,
                item[1].asset_id,
            ),
        )
    )
    values = tuple(position.value for _account_id, position in ordered_positions)
    if _sum(values, _MONEY) != investment_value:
        raise _fail()
    percentages = _percentages(values, investment_value)
    return tuple(
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
            allocation_pct=allocation_pct,
        )
        for (account_id, position), allocation_pct in zip(
            ordered_positions, percentages, strict=True
        )
    )


def build_dashboard_snapshot_view(
    portfolio: MultiAccountPortfolioView,
    account_presentations: tuple[AccountPortfolioPresentationView, ...] | None = None,
) -> DashboardSnapshotView:
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
        primary_by_account: dict[str, DashboardAccountCard] = {}
        positions: list[tuple[str, PortfolioPositionView]] = []
        investment_account_count = 0
        liability_account_count = 0
        for account_view in portfolio.accounts:
            card, scoped_positions, is_investment, is_liability = _account_card(
                account_view,
                output_currency=currency,
                account_ids=account_ids,
                snapshot_ids=snapshot_ids,
            )
            if card.snapshot_id != card.primary_snapshot_id:
                raise _fail()
            primary_by_account[card.account_id] = card
            positions.extend(scoped_positions)
            investment_account_count += int(is_investment)
            liability_account_count += int(is_liability)
        if summary.account_count != len(primary_by_account) or summary.position_count != len(
            positions
        ):
            raise _fail()
        presentation_account_ids: set[str] = set()
        presentation_snapshot_ids: set[str] = set()
        cards: list[DashboardAccountCard] = []
        if account_presentations is None:
            presentation_views = tuple(
                (account, currency, account.snapshot_id) for account in portfolio.accounts
            )
        else:
            if type(account_presentations) is not tuple or len(account_presentations) != len(
                portfolio.accounts
            ):
                raise _fail()
            presentation_views = tuple(
                (
                    MultiAccountPortfolioAccountView(
                        snapshot_id=presentation.presentation_snapshot_id,
                        account=presentation.account,
                        source=presentation.source,
                        summary=presentation.summary,
                        positions=presentation.positions,
                    ),
                    presentation.currency,
                    presentation.primary_snapshot_id,
                )
                for presentation in account_presentations
                if type(presentation) is AccountPortfolioPresentationView
            )
            if len(presentation_views) != len(account_presentations):
                raise _fail()
        for account_view, presentation_currency, primary_snapshot_id in presentation_views:
            card, _presentation_positions, is_investment, is_liability = _account_card(
                account_view,
                output_currency=presentation_currency,
                account_ids=presentation_account_ids,
                snapshot_ids=presentation_snapshot_ids,
                primary_snapshot_id=primary_snapshot_id,
            )
            primary = primary_by_account.get(card.account_id)
            if (
                primary is None
                or card.primary_snapshot_id != primary.snapshot_id
                or card.name != primary.name
                or card.account_type is not primary.account_type
                or card.account_currency != primary.account_currency
                or (
                    account_presentations is not None
                    and card.output_currency != card.account_currency
                )
                or is_investment is not (primary.account_type in _INVESTMENT_ACCOUNT_TYPES)
                or is_liability is not (primary.account_type in _LIABILITY_ACCOUNT_TYPES)
            ):
                raise _fail()
            cards.append(card)
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
            liability_account_count=liability_account_count,
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
