"""Pure deterministic aggregation of complete account portfolio snapshot views."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.modules.portfolio_snapshot.aggregate_models import (
    MultiAccountPortfolioAccountView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioAccountView,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)

_ERROR_MESSAGE = "Portfolio snapshot views cannot produce a complete multi-account view."
_MONEY = (18, 6)
_MONEY_LIMIT = Decimal("1000000000000")
_POSTGRES_INTEGER_MAX = 2_147_483_647


class MultiAccountPortfolioProjectionError(ValueError):
    """Raised when complete account views cannot form one coherent aggregate."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


def _fail() -> MultiAccountPortfolioProjectionError:
    return MultiAccountPortfolioProjectionError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _text(value)
    if len(currency) != 3 or any(character < "A" or character > "Z" for character in currency):
        raise _fail()
    return currency


def _exact_money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    _, scale = _MONEY
    try:
        with localcontext() as context:
            context.prec = 112
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or value.copy_abs() >= _MONEY_LIMIT:
        raise _fail()
    return value


def _sum_money(values: tuple[object, ...]) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = sum((_exact_money(value) for value in values), Decimal(0))
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact_money(result)


def _validate_view(view: object) -> PortfolioSnapshotView:
    if (
        not isinstance(view, PortfolioSnapshotView)
        or not isinstance(view.account, PortfolioAccountView)
        or not isinstance(view.summary, PortfolioSummaryView)
        or not isinstance(view.positions, tuple)
        or not isinstance(view.source, SnapshotSource)
        or not isinstance(view.timestamp, datetime)
        or view.timestamp.tzinfo is not None
        or view.timestamp.microsecond % 1_000
        or not isinstance(view.granularity, SnapshotGranularity)
        or not isinstance(view.calculation_version, int)
        or isinstance(view.calculation_version, bool)
        or not 1 <= view.calculation_version <= _POSTGRES_INTEGER_MAX
        or view.summary.position_count != len(view.positions)
    ):
        raise _fail()
    _text(view.snapshot_id)
    _text(view.account.account_id)
    _currency(view.currency)
    return view


def _summary(
    views: tuple[PortfolioSnapshotView, ...],
) -> MultiAccountPortfolioSummary:
    cash_value = _sum_money(tuple(view.summary.cash_value for view in views))
    investment_value = _sum_money(tuple(view.summary.investment_value for view in views))
    investment_cost_basis = _sum_money(tuple(view.summary.investment_cost_basis for view in views))
    liabilities_value = _sum_money(tuple(view.summary.liabilities_value for view in views))
    total_value = _sum_money(tuple(view.summary.total_value for view in views))
    net_deposits_value = _sum_money(tuple(view.summary.net_deposits_value for view in views))
    realized_pnl_value = _sum_money(tuple(view.summary.realized_pnl_value for view in views))
    unrealized_pnl_value = _sum_money(tuple(view.summary.unrealized_pnl_value for view in views))
    fees_value = _sum_money(tuple(view.summary.fees_value for view in views))
    taxes_value = _sum_money(tuple(view.summary.taxes_value for view in views))
    try:
        with localcontext() as context:
            context.prec = 112
            expected_total = cash_value + investment_value - liabilities_value
            expected_unrealized = investment_value - investment_cost_basis
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    position_count = sum(len(view.positions) for view in views)
    if (
        total_value != expected_total
        or unrealized_pnl_value != expected_unrealized
        or position_count != sum(view.summary.position_count for view in views)
    ):
        raise _fail()
    return MultiAccountPortfolioSummary(
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=total_value,
        net_deposits_value=net_deposits_value,
        realized_pnl_value=realized_pnl_value,
        unrealized_pnl_value=unrealized_pnl_value,
        fees_value=fees_value,
        taxes_value=taxes_value,
        account_count=len(views),
        position_count=position_count,
    )


def build_multi_account_portfolio_view(
    views: tuple[PortfolioSnapshotView, ...],
) -> MultiAccountPortfolioView:
    """Aggregate a coherent non-empty tuple of complete 5L-A views."""

    try:
        if not isinstance(views, tuple) or not views:
            raise _fail()
        validated = tuple(_validate_view(view) for view in views)
        ordered = tuple(
            sorted(
                validated,
                key=lambda view: (view.account.account_id, view.snapshot_id),
            )
        )
        reference = ordered[0]
        account_ids: set[str] = set()
        snapshot_ids: set[str] = set()
        for view in ordered:
            account_id = view.account.account_id
            snapshot_id = view.snapshot_id
            if (
                account_id in account_ids
                or snapshot_id in snapshot_ids
                or view.timestamp != reference.timestamp
                or view.granularity is not reference.granularity
                or view.currency != reference.currency
                or view.calculation_version != reference.calculation_version
            ):
                raise _fail()
            account_ids.add(account_id)
            snapshot_ids.add(snapshot_id)
        summary = _summary(ordered)
        accounts = tuple(
            MultiAccountPortfolioAccountView(
                snapshot_id=view.snapshot_id,
                account=view.account,
                source=view.source,
                summary=view.summary,
                positions=view.positions,
            )
            for view in ordered
        )
        return MultiAccountPortfolioView(
            timestamp=reference.timestamp,
            granularity=reference.granularity,
            currency=reference.currency,
            calculation_version=reference.calculation_version,
            summary=summary,
            accounts=accounts,
        )
    except MultiAccountPortfolioProjectionError:
        raise
    except (AttributeError, InvalidOperation, OverflowError, TypeError, ValueError) as exc:
        raise _fail() from exc
