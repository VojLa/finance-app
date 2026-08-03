"""Pure deterministic NetWorthSnapshot valuation projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Numeric

from app.db.models.common import MONEY, QUANTITY
from app.db.models.enums import AccountType, SnapshotGranularity

_ERROR_MESSAGE = "Account snapshots cannot produce a complete net worth projection."
_TIMESTAMP_PRECISION = 3
_POSTGRES_INTEGER_MAX = 2_147_483_647
_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_CASH_ACCOUNT_TYPES = {
    AccountType.bank,
    AccountType.cash,
    AccountType.savings,
}
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}
_SUPPORTED_ACCOUNT_TYPES = (
    _CASH_ACCOUNT_TYPES | _INVESTMENT_ACCOUNT_TYPES | _LIABILITY_ACCOUNT_TYPES
)


class NetWorthProjectionStateError(ValueError):
    """Raised when exact account snapshots cannot produce one net-worth projection."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class NetWorthCurrencyAmount:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AccountNetWorthEvidence:
    snapshot_id: str
    account_id: str
    account_type: AccountType
    account_currency: str
    snapshot_currency: str
    timestamp: datetime
    granularity: SnapshotGranularity
    total_value: Decimal
    cash_value: Decimal
    investment_value: Decimal
    liabilities_value: Decimal
    cash_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None = None
    investment_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None = None
    liabilities_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None = None


@dataclass(frozen=True, slots=True)
class NetWorthProjectionInput:
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    account_snapshots: tuple[AccountNetWorthEvidence, ...]


@dataclass(frozen=True, slots=True)
class ExpectedNetWorthAccountContribution:
    snapshot_id: str
    account_id: str
    account_type: AccountType
    cash_value: Decimal
    portfolio_value: Decimal
    assets_value: Decimal
    liabilities_value: Decimal
    net_value: Decimal


@dataclass(frozen=True, slots=True)
class NetWorthAccountTypeAmount:
    account_type: AccountType
    assets_value: Decimal
    liabilities_value: Decimal
    net_value: Decimal


@dataclass(frozen=True, slots=True)
class ExpectedNetWorthProjection:
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    cash_value: Decimal
    portfolio_value: Decimal
    assets_value: Decimal
    liabilities_value: Decimal
    net_worth_value: Decimal
    account_count: int
    accounts: tuple[ExpectedNetWorthAccountContribution, ...]
    account_type_breakdown: tuple[NetWorthAccountTypeAmount, ...]
    cash_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None
    portfolio_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None
    liabilities_value_by_currency: tuple[NetWorthCurrencyAmount, ...] | None
    total_net_worth_by_currency: tuple[NetWorthCurrencyAmount, ...] | None


def _fail() -> NetWorthProjectionStateError:
    return NetWorthProjectionStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise _fail()
    return currency


def _exact(value: object, numeric: Numeric) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric types must define precision and scale.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            scaled = value.quantize(quantum)
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail()
    return value


def _add(left: Decimal, right: Decimal, *, numeric: Numeric) -> Decimal:
    precision = numeric.precision
    if precision is None:
        raise RuntimeError("Canonical numeric types must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 4, 112)
        result = _exact(left, numeric) + _exact(right, numeric)
    return _exact(result, numeric)


def _subtract(left: Decimal, right: Decimal, *, numeric: Numeric) -> Decimal:
    precision = numeric.precision
    if precision is None:
        raise RuntimeError("Canonical numeric types must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 4, 112)
        result = _exact(left, numeric) - _exact(right, numeric)
    return _exact(result, numeric)


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % (10 ** (6 - _TIMESTAMP_PRECISION))
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


def _breakdown(
    value: object,
    *,
    numeric: Numeric,
    nonnegative: bool,
) -> tuple[NetWorthCurrencyAmount, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise _fail()
    amounts: dict[str, Decimal] = {}
    for item in value:
        if not isinstance(item, NetWorthCurrencyAmount):
            raise _fail()
        currency = _currency(item.currency)
        amount = _exact(item.amount, numeric)
        if currency in amounts or (nonnegative and amount < 0):
            raise _fail()
        amounts[currency] = amount
    return tuple(
        NetWorthCurrencyAmount(currency=currency, amount=amounts[currency])
        for currency in sorted(amounts)
    )


def _merge_breakdowns(
    breakdowns: list[tuple[NetWorthCurrencyAmount, ...] | None],
    *,
    numeric: Numeric,
) -> tuple[NetWorthCurrencyAmount, ...] | None:
    if any(breakdown is None for breakdown in breakdowns):
        return None
    amounts: dict[str, Decimal] = {}
    for breakdown in breakdowns:
        assert breakdown is not None
        for item in breakdown:
            amounts[item.currency] = _add(
                amounts.get(item.currency, Decimal(0)),
                item.amount,
                numeric=numeric,
            )
    return tuple(
        NetWorthCurrencyAmount(currency=currency, amount=amounts[currency])
        for currency in sorted(amounts)
    )


def _net_breakdown(
    cash: tuple[NetWorthCurrencyAmount, ...] | None,
    portfolio: tuple[NetWorthCurrencyAmount, ...] | None,
    liabilities: tuple[NetWorthCurrencyAmount, ...] | None,
    *,
    portfolio_value: Decimal,
    liabilities_value: Decimal,
) -> tuple[NetWorthCurrencyAmount, ...] | None:
    if portfolio is None and portfolio_value == 0:
        portfolio = ()
    if liabilities is None and liabilities_value == 0:
        liabilities = ()
    if cash is None or portfolio is None or liabilities is None:
        return None
    amounts: dict[str, Decimal] = {}
    for item in cash:
        amounts[item.currency] = _add(
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            numeric=QUANTITY,
        )
    for item in portfolio:
        amounts[item.currency] = _add(
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            numeric=QUANTITY,
        )
    for item in liabilities:
        amounts[item.currency] = _subtract(
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            numeric=QUANTITY,
        )
    return tuple(
        NetWorthCurrencyAmount(currency=currency, amount=amounts[currency])
        for currency in sorted(amounts)
    )


def _validate_evidence(
    evidence: object,
    *,
    expected_timestamp: datetime,
    expected_granularity: SnapshotGranularity,
    expected_currency: str,
) -> tuple[
    ExpectedNetWorthAccountContribution,
    tuple[NetWorthCurrencyAmount, ...] | None,
    tuple[NetWorthCurrencyAmount, ...] | None,
    tuple[NetWorthCurrencyAmount, ...] | None,
]:
    if not isinstance(evidence, AccountNetWorthEvidence):
        raise _fail()
    snapshot_id = _nonblank(evidence.snapshot_id)
    account_id = _nonblank(evidence.account_id)
    _currency(evidence.account_currency)
    if (
        not isinstance(evidence.account_type, AccountType)
        or evidence.account_type not in _SUPPORTED_ACCOUNT_TYPES
        or _currency(evidence.snapshot_currency) != expected_currency
        or _timestamp(evidence.timestamp) != expected_timestamp
        or not isinstance(evidence.granularity, SnapshotGranularity)
        or evidence.granularity is not expected_granularity
    ):
        raise _fail()

    cash = _exact(evidence.cash_value, MONEY)
    portfolio = _exact(evidence.investment_value, MONEY)
    liabilities = _exact(evidence.liabilities_value, MONEY)
    total = _exact(evidence.total_value, MONEY)
    if portfolio < 0 or liabilities < 0:
        raise _fail()
    assets = _add(cash, portfolio, numeric=MONEY)
    net = _subtract(assets, liabilities, numeric=MONEY)
    if net != total:
        raise _fail()

    cash_breakdown = _breakdown(
        evidence.cash_value_by_currency,
        numeric=MONEY,
        nonnegative=False,
    )
    portfolio_breakdown = _breakdown(
        evidence.investment_value_by_currency,
        numeric=QUANTITY,
        nonnegative=True,
    )
    liability_breakdown = _breakdown(
        evidence.liabilities_value_by_currency,
        numeric=MONEY,
        nonnegative=True,
    )

    if evidence.account_type in _INVESTMENT_ACCOUNT_TYPES:
        if liabilities != 0 or (liability_breakdown is not None and liability_breakdown != ()):
            raise _fail()
    elif evidence.account_type in _CASH_ACCOUNT_TYPES:
        if portfolio != 0 or liabilities != 0:
            raise _fail()
        if portfolio_breakdown is not None and portfolio_breakdown != ():
            raise _fail()
        if liability_breakdown is not None and liability_breakdown != ():
            raise _fail()
    else:
        if cash != 0 or portfolio != 0:
            raise _fail()
        if cash_breakdown is not None and cash_breakdown != ():
            raise _fail()
        if portfolio_breakdown is not None and portfolio_breakdown != ():
            raise _fail()
        if liability_breakdown is not None and liability_breakdown != (
            NetWorthCurrencyAmount(currency=expected_currency, amount=liabilities),
        ):
            raise _fail()

    return (
        ExpectedNetWorthAccountContribution(
            snapshot_id=snapshot_id,
            account_id=account_id,
            account_type=evidence.account_type,
            cash_value=cash,
            portfolio_value=portfolio,
            assets_value=assets,
            liabilities_value=liabilities,
            net_value=net,
        ),
        cash_breakdown,
        portfolio_breakdown,
        liability_breakdown,
    )


def build_net_worth_projection(evidence: NetWorthProjectionInput) -> ExpectedNetWorthProjection:
    """Build one exact immutable net-worth valuation without I/O or mutation."""

    if not isinstance(evidence, NetWorthProjectionInput):
        raise _fail()
    user_id = _nonblank(evidence.user_id)
    if not isinstance(evidence.granularity, SnapshotGranularity):
        raise _fail()
    timestamp = _aligned_timestamp(evidence.timestamp, evidence.granularity)
    currency = _currency(evidence.currency)
    calculation_version = _calculation_version(evidence.calculation_version)
    if not isinstance(evidence.account_snapshots, tuple):
        raise _fail()

    validated: list[
        tuple[
            ExpectedNetWorthAccountContribution,
            tuple[NetWorthCurrencyAmount, ...] | None,
            tuple[NetWorthCurrencyAmount, ...] | None,
            tuple[NetWorthCurrencyAmount, ...] | None,
        ]
    ] = []
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    cash_breakdowns: list[tuple[NetWorthCurrencyAmount, ...] | None] = []
    portfolio_breakdowns: list[tuple[NetWorthCurrencyAmount, ...] | None] = []
    liability_breakdowns: list[tuple[NetWorthCurrencyAmount, ...] | None] = []
    for item in evidence.account_snapshots:
        contribution, cash_breakdown, portfolio_breakdown, liability_breakdown = _validate_evidence(
            item,
            expected_timestamp=timestamp,
            expected_granularity=evidence.granularity,
            expected_currency=currency,
        )
        if contribution.account_id in account_ids or contribution.snapshot_id in snapshot_ids:
            raise _fail()
        account_ids.add(contribution.account_id)
        snapshot_ids.add(contribution.snapshot_id)
        validated.append(
            (
                contribution,
                cash_breakdown,
                portfolio_breakdown,
                liability_breakdown,
            )
        )

    ordered = tuple(
        sorted(
            validated,
            key=lambda item: (item[0].account_id, item[0].snapshot_id),
        )
    )
    accounts = tuple(item[0] for item in ordered)
    cash_breakdowns.extend(item[1] for item in ordered)
    portfolio_breakdowns.extend(item[2] for item in ordered)
    liability_breakdowns.extend(item[3] for item in ordered)
    cash_value = Decimal(0)
    portfolio_value = Decimal(0)
    liabilities_value = Decimal(0)
    account_net_total = Decimal(0)
    by_type: dict[AccountType, tuple[Decimal, Decimal, Decimal]] = {}
    for contribution in accounts:
        cash_value = _add(cash_value, contribution.cash_value, numeric=MONEY)
        portfolio_value = _add(
            portfolio_value,
            contribution.portfolio_value,
            numeric=MONEY,
        )
        liabilities_value = _add(
            liabilities_value,
            contribution.liabilities_value,
            numeric=MONEY,
        )
        account_net_total = _add(
            account_net_total,
            contribution.net_value,
            numeric=MONEY,
        )
        type_assets, type_liabilities, type_net = by_type.get(
            contribution.account_type,
            (Decimal(0), Decimal(0), Decimal(0)),
        )
        by_type[contribution.account_type] = (
            _add(type_assets, contribution.assets_value, numeric=MONEY),
            _add(
                type_liabilities,
                contribution.liabilities_value,
                numeric=MONEY,
            ),
            _add(type_net, contribution.net_value, numeric=MONEY),
        )

    assets_value = _add(cash_value, portfolio_value, numeric=MONEY)
    net_worth_value = _subtract(assets_value, liabilities_value, numeric=MONEY)
    if net_worth_value != account_net_total:
        raise _fail()
    account_type_breakdown = tuple(
        NetWorthAccountTypeAmount(
            account_type=account_type,
            assets_value=values[0],
            liabilities_value=values[1],
            net_value=values[2],
        )
        for account_type, values in sorted(by_type.items(), key=lambda item: item[0].value)
    )
    aggregate_cash_breakdown = _merge_breakdowns(cash_breakdowns, numeric=MONEY)
    aggregate_portfolio_breakdown = _merge_breakdowns(
        portfolio_breakdowns,
        numeric=QUANTITY,
    )
    aggregate_liability_breakdown = _merge_breakdowns(
        liability_breakdowns,
        numeric=MONEY,
    )

    return ExpectedNetWorthProjection(
        user_id=user_id,
        timestamp=timestamp,
        granularity=evidence.granularity,
        currency=currency,
        calculation_version=calculation_version,
        cash_value=cash_value,
        portfolio_value=portfolio_value,
        assets_value=assets_value,
        liabilities_value=liabilities_value,
        net_worth_value=net_worth_value,
        account_count=len(accounts),
        accounts=accounts,
        account_type_breakdown=account_type_breakdown,
        cash_value_by_currency=aggregate_cash_breakdown,
        portfolio_value_by_currency=aggregate_portfolio_breakdown,
        liabilities_value_by_currency=aggregate_liability_breakdown,
        total_net_worth_by_currency=_net_breakdown(
            aggregate_cash_breakdown,
            aggregate_portfolio_breakdown,
            aggregate_liability_breakdown,
            portfolio_value=portfolio_value,
            liabilities_value=liabilities_value,
        ),
    )
