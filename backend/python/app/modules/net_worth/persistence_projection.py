"""Pure projection into the complete physical NetWorthSnapshot row contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from uuid import UUID, uuid5

from sqlalchemy import Numeric

from app.db.models.common import MONEY, QUANTITY, TIMESTAMP
from app.db.models.enums import AccountType, SnapshotGranularity, SnapshotSource
from app.modules.net_worth.evidence_service import (
    CompleteNetWorthEvidence,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.projection import (
    ExpectedNetWorthAccountContribution,
    ExpectedNetWorthProjection,
    NetWorthAccountTypeAmount,
    NetWorthCurrencyAmount,
)

_ERROR_MESSAGE = "Net-worth evidence is not physically persistable."
_SNAPSHOT_ID_NAMESPACE = UUID("1fc1e31d-af26-5769-872b-97496885d97d")
_POSTGRES_INTEGER_MAX = 2_147_483_647
_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}
_SUPPORTED_ACCOUNT_TYPES = _INVESTMENT_ACCOUNT_TYPES | _LIABILITY_ACCOUNT_TYPES


class NetWorthSnapshotPersistenceProjectionError(ValueError):
    """Raised when complete evidence cannot populate one physical snapshot row."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class CanonicalNetWorthJsonObject:
    """Immutable ordered scalar JSON object with a fresh materialization boundary."""

    entries: tuple[tuple[str, str], ...]

    def to_json(self) -> dict[str, object]:
        return dict(self.entries)


@dataclass(frozen=True, slots=True)
class NetWorthSnapshotPersistenceMetadata:
    source: SnapshotSource
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool


@dataclass(frozen=True, slots=True)
class ExpectedNetWorthSnapshotRow:
    id: str
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    currency: str
    cash_value: Decimal
    portfolio_value: Decimal
    liabilities_value: Decimal
    total_net_worth: Decimal
    is_recalculated: bool
    calculated_at: datetime
    calculation_version: int
    created_at: datetime
    cash_value_by_currency: CanonicalNetWorthJsonObject | None
    portfolio_value_by_currency: CanonicalNetWorthJsonObject | None
    liabilities_value_by_currency: CanonicalNetWorthJsonObject | None
    total_net_worth_by_currency: CanonicalNetWorthJsonObject | None
    exchange_rates: CanonicalNetWorthJsonObject | None

    def model_values(self) -> dict[str, object]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "granularity": self.granularity,
            "source": self.source,
            "currency": self.currency,
            "cash_value": self.cash_value,
            "portfolio_value": self.portfolio_value,
            "liabilities_value": self.liabilities_value,
            "total_net_worth": self.total_net_worth,
            "is_recalculated": self.is_recalculated,
            "calculated_at": self.calculated_at,
            "calculation_version": self.calculation_version,
            "created_at": self.created_at,
            "cash_value_by_currency": _json(self.cash_value_by_currency),
            "portfolio_value_by_currency": _json(self.portfolio_value_by_currency),
            "liabilities_value_by_currency": _json(self.liabilities_value_by_currency),
            "total_net_worth_by_currency": _json(self.total_net_worth_by_currency),
            "exchange_rates": _json(self.exchange_rates),
        }


@dataclass(frozen=True, slots=True)
class NetWorthSnapshotPersistenceAudit:
    selected_account_ids: tuple[str, ...]
    selected_account_snapshot_ids: tuple[str, ...]
    selected_identities: tuple[SelectedAccountSnapshotIdentity, ...]


@dataclass(frozen=True, slots=True)
class ExpectedNetWorthSnapshotPersistence:
    snapshot: ExpectedNetWorthSnapshotRow
    audit: NetWorthSnapshotPersistenceAudit


def _fail() -> NetWorthSnapshotPersistenceProjectionError:
    return NetWorthSnapshotPersistenceProjectionError()


def _json(value: CanonicalNetWorthJsonObject | None) -> dict[str, object] | None:
    return None if value is None else value.to_json()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
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


def _exact(
    value: object,
    numeric: Numeric,
    *,
    nonnegative: bool = False,
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
    ):
        raise _fail()
    return value


def _calculate(
    operation: str,
    left: Decimal,
    right: Decimal,
    numeric: Numeric,
) -> Decimal:
    precision = numeric.precision
    if precision is None:
        raise RuntimeError("Canonical numeric types must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 4, 112)
        if operation == "add":
            result = left + right
        elif operation == "subtract":
            result = left - right
        else:
            raise RuntimeError("Unsupported exact calculation.")
    return _exact(result, numeric)


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    result = Decimal(0)
    for value in values:
        result = _calculate("add", result, value, MONEY)
    return result


def _calculation_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _decimal_string(value: Decimal, numeric: Numeric) -> str:
    scale = numeric.scale
    if scale is None:
        raise RuntimeError("Canonical numeric types must define scale.")
    return f"{value:.{scale}f}"


def _validated_breakdown(
    value: object,
    *,
    numeric: Numeric,
    scalar: Decimal,
    output_currency: str,
    nonnegative: bool,
) -> tuple[NetWorthCurrencyAmount, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise _fail()
    entries: list[NetWorthCurrencyAmount] = []
    currencies: list[str] = []
    amounts: list[Decimal] = []
    for item in value:
        if not isinstance(item, NetWorthCurrencyAmount):
            raise _fail()
        currency = _currency(item.currency)
        amount = _exact(item.amount, numeric, nonnegative=nonnegative)
        if currency in currencies:
            raise _fail()
        currencies.append(currency)
        amounts.append(amount)
        entries.append(NetWorthCurrencyAmount(currency=currency, amount=amount))
    if currencies != sorted(currencies):
        raise _fail()
    if not entries and scalar != 0:
        raise _fail()
    if len(entries) == 1 and currencies[0] == output_currency and amounts[0] != scalar:
        raise _fail()
    return tuple(entries)


def _expected_total_breakdown(
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
        amounts[item.currency] = _calculate(
            "add",
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            QUANTITY,
        )
    for item in portfolio:
        amounts[item.currency] = _calculate(
            "add",
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            QUANTITY,
        )
    for item in liabilities:
        amounts[item.currency] = _calculate(
            "subtract",
            amounts.get(item.currency, Decimal(0)),
            item.amount,
            QUANTITY,
        )
    return tuple(
        NetWorthCurrencyAmount(currency=currency, amount=amounts[currency])
        for currency in sorted(amounts)
    )


def _serialize_breakdown(
    value: tuple[NetWorthCurrencyAmount, ...] | None,
    *,
    numeric: Numeric,
) -> CanonicalNetWorthJsonObject | None:
    if value is None:
        return None
    return CanonicalNetWorthJsonObject(
        tuple((item.currency, _decimal_string(item.amount, numeric)) for item in value)
    )


def _validate_contributions(
    projection: ExpectedNetWorthProjection,
) -> tuple[ExpectedNetWorthAccountContribution, ...]:
    if not isinstance(projection.accounts, tuple):
        raise _fail()
    accounts: list[ExpectedNetWorthAccountContribution] = []
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    grouped: dict[AccountType, tuple[Decimal, Decimal, Decimal]] = {}
    for contribution in projection.accounts:
        if not isinstance(contribution, ExpectedNetWorthAccountContribution):
            raise _fail()
        account_id = _nonblank(contribution.account_id)
        snapshot_id = _nonblank(contribution.snapshot_id)
        if (
            account_id in account_ids
            or snapshot_id in snapshot_ids
            or not isinstance(contribution.account_type, AccountType)
            or contribution.account_type not in _SUPPORTED_ACCOUNT_TYPES
        ):
            raise _fail()
        cash = _exact(contribution.cash_value, MONEY)
        portfolio = _exact(contribution.portfolio_value, MONEY, nonnegative=True)
        assets = _exact(contribution.assets_value, MONEY)
        liabilities = _exact(contribution.liabilities_value, MONEY, nonnegative=True)
        net = _exact(contribution.net_value, MONEY)
        if (
            _calculate("add", cash, portfolio, MONEY) != assets
            or _calculate("subtract", assets, liabilities, MONEY) != net
        ):
            raise _fail()
        if contribution.account_type in _INVESTMENT_ACCOUNT_TYPES:
            if liabilities != 0:
                raise _fail()
        elif cash != 0 or portfolio != 0 or assets != 0 or net != -liabilities:
            raise _fail()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        accounts.append(contribution)
        type_assets, type_liabilities, type_net = grouped.get(
            contribution.account_type,
            (Decimal(0), Decimal(0), Decimal(0)),
        )
        grouped[contribution.account_type] = (
            _calculate("add", type_assets, assets, MONEY),
            _calculate("add", type_liabilities, liabilities, MONEY),
            _calculate("add", type_net, net, MONEY),
        )
    if accounts != sorted(accounts, key=lambda item: (item.account_id, item.snapshot_id)):
        raise _fail()
    _validate_type_breakdown(projection.account_type_breakdown, grouped)
    return tuple(accounts)


def _validate_type_breakdown(
    value: object,
    expected: dict[AccountType, tuple[Decimal, Decimal, Decimal]],
) -> None:
    if not isinstance(value, tuple):
        raise _fail()
    types: list[AccountType] = []
    actual: dict[AccountType, tuple[Decimal, Decimal, Decimal]] = {}
    for item in value:
        if (
            not isinstance(item, NetWorthAccountTypeAmount)
            or not isinstance(item.account_type, AccountType)
            or item.account_type not in _SUPPORTED_ACCOUNT_TYPES
            or item.account_type in actual
        ):
            raise _fail()
        assets = _exact(item.assets_value, MONEY)
        liabilities = _exact(item.liabilities_value, MONEY, nonnegative=True)
        net = _exact(item.net_value, MONEY)
        if _calculate("subtract", assets, liabilities, MONEY) != net:
            raise _fail()
        types.append(item.account_type)
        actual[item.account_type] = (assets, liabilities, net)
    if types != sorted(types, key=lambda item: item.value) or actual != expected:
        raise _fail()


def _validate_projection(
    value: object,
) -> tuple[
    ExpectedNetWorthProjection,
    tuple[ExpectedNetWorthAccountContribution, ...],
    CanonicalNetWorthJsonObject | None,
    CanonicalNetWorthJsonObject | None,
    CanonicalNetWorthJsonObject | None,
    CanonicalNetWorthJsonObject | None,
]:
    if not isinstance(value, ExpectedNetWorthProjection):
        raise _fail()
    user_id = _nonblank(value.user_id)
    if not isinstance(value.granularity, SnapshotGranularity):
        raise _fail()
    timestamp = _aligned_timestamp(value.timestamp, value.granularity)
    currency = _currency(value.currency)
    calculation_version = _calculation_version(value.calculation_version)
    cash = _exact(value.cash_value, MONEY)
    portfolio = _exact(value.portfolio_value, MONEY, nonnegative=True)
    assets = _exact(value.assets_value, MONEY)
    liabilities = _exact(value.liabilities_value, MONEY, nonnegative=True)
    total = _exact(value.net_worth_value, MONEY)
    if (
        _calculate("add", cash, portfolio, MONEY) != assets
        or _calculate("subtract", assets, liabilities, MONEY) != total
    ):
        raise _fail()
    accounts = _validate_contributions(value)
    if (
        not isinstance(value.account_count, int)
        or isinstance(value.account_count, bool)
        or value.account_count != len(accounts)
        or _sum(tuple(item.cash_value for item in accounts)) != cash
        or _sum(tuple(item.portfolio_value for item in accounts)) != portfolio
        or _sum(tuple(item.liabilities_value for item in accounts)) != liabilities
        or _sum(tuple(item.net_value for item in accounts)) != total
    ):
        raise _fail()
    cash_values = _validated_breakdown(
        value.cash_value_by_currency,
        numeric=MONEY,
        scalar=cash,
        output_currency=currency,
        nonnegative=False,
    )
    portfolio_values = _validated_breakdown(
        value.portfolio_value_by_currency,
        numeric=QUANTITY,
        scalar=portfolio,
        output_currency=currency,
        nonnegative=True,
    )
    liability_values = _validated_breakdown(
        value.liabilities_value_by_currency,
        numeric=MONEY,
        scalar=liabilities,
        output_currency=currency,
        nonnegative=True,
    )
    total_values = _validated_breakdown(
        value.total_net_worth_by_currency,
        numeric=QUANTITY,
        scalar=total,
        output_currency=currency,
        nonnegative=False,
    )
    expected_total_values = _expected_total_breakdown(
        cash_values,
        portfolio_values,
        liability_values,
        portfolio_value=portfolio,
        liabilities_value=liabilities,
    )
    if total_values != expected_total_values:
        raise _fail()
    cash_breakdown = _serialize_breakdown(cash_values, numeric=MONEY)
    portfolio_breakdown = _serialize_breakdown(portfolio_values, numeric=QUANTITY)
    liability_breakdown = _serialize_breakdown(liability_values, numeric=MONEY)
    total_breakdown = _serialize_breakdown(total_values, numeric=QUANTITY)
    canonical = ExpectedNetWorthProjection(
        user_id=user_id,
        timestamp=timestamp,
        granularity=value.granularity,
        currency=currency,
        calculation_version=calculation_version,
        cash_value=cash,
        portfolio_value=portfolio,
        assets_value=assets,
        liabilities_value=liabilities,
        net_worth_value=total,
        account_count=value.account_count,
        accounts=accounts,
        account_type_breakdown=value.account_type_breakdown,
        cash_value_by_currency=cash_values,
        portfolio_value_by_currency=portfolio_values,
        liabilities_value_by_currency=liability_values,
        total_net_worth_by_currency=total_values,
    )
    return (
        canonical,
        accounts,
        cash_breakdown,
        portfolio_breakdown,
        liability_breakdown,
        total_breakdown,
    )


def _validate_audit(
    evidence: CompleteNetWorthEvidence,
    accounts: tuple[ExpectedNetWorthAccountContribution, ...],
) -> NetWorthSnapshotPersistenceAudit:
    if (
        not isinstance(evidence.selected_account_ids, tuple)
        or not isinstance(evidence.selected_account_snapshot_ids, tuple)
        or not isinstance(evidence.selected_identities, tuple)
    ):
        raise _fail()
    identities: list[SelectedAccountSnapshotIdentity] = []
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    for identity in evidence.selected_identities:
        if not isinstance(identity, SelectedAccountSnapshotIdentity):
            raise _fail()
        account_id = _nonblank(identity.account_id)
        snapshot_id = _nonblank(identity.snapshot_id)
        if account_id in account_ids or snapshot_id in snapshot_ids:
            raise _fail()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        identities.append(identity)
    if identities != sorted(
        identities,
        key=lambda identity: (identity.account_id, identity.snapshot_id),
    ):
        raise _fail()
    expected_account_ids = tuple(identity.account_id for identity in identities)
    expected_snapshot_ids = tuple(identity.snapshot_id for identity in identities)
    selected_account_ids = tuple(_nonblank(value) for value in evidence.selected_account_ids)
    selected_snapshot_ids = tuple(
        _nonblank(value) for value in evidence.selected_account_snapshot_ids
    )
    contribution_pairs = tuple((item.account_id, item.snapshot_id) for item in accounts)
    identity_pairs = tuple((item.account_id, item.snapshot_id) for item in identities)
    if (
        selected_account_ids != expected_account_ids
        or selected_snapshot_ids != expected_snapshot_ids
        or identity_pairs != contribution_pairs
        or len(identities) != len(accounts)
    ):
        raise _fail()
    return NetWorthSnapshotPersistenceAudit(
        selected_account_ids=selected_account_ids,
        selected_account_snapshot_ids=selected_snapshot_ids,
        selected_identities=tuple(identities),
    )


def _snapshot_id(
    *,
    user_id: str,
    timestamp: datetime,
    currency: str,
    granularity: SnapshotGranularity,
) -> str:
    payload = "\0".join(
        (
            user_id,
            timestamp.isoformat(timespec="milliseconds"),
            currency,
            granularity.value,
        )
    )
    return str(uuid5(_SNAPSHOT_ID_NAMESPACE, payload))


def build_net_worth_snapshot_persistence_projection(
    evidence: CompleteNetWorthEvidence,
    metadata: NetWorthSnapshotPersistenceMetadata,
) -> ExpectedNetWorthSnapshotPersistence:
    """Map complete 5J-B evidence into an immutable physical row contract."""

    try:
        if not isinstance(evidence, CompleteNetWorthEvidence) or not isinstance(
            metadata,
            NetWorthSnapshotPersistenceMetadata,
        ):
            raise _fail()
        if (
            not isinstance(metadata.source, SnapshotSource)
            or not isinstance(metadata.is_recalculated, bool)
            or metadata.is_recalculated
            is not (metadata.source is SnapshotSource.manual_recalculation)
        ):
            raise _fail()
        calculated_at = _timestamp(metadata.calculated_at)
        created_at = _timestamp(metadata.created_at)
        (
            projection,
            accounts,
            cash_breakdown,
            portfolio_breakdown,
            liability_breakdown,
            total_breakdown,
        ) = _validate_projection(evidence.projection)
        audit = _validate_audit(evidence, accounts)
        snapshot = ExpectedNetWorthSnapshotRow(
            id=_snapshot_id(
                user_id=projection.user_id,
                timestamp=projection.timestamp,
                currency=projection.currency,
                granularity=projection.granularity,
            ),
            user_id=projection.user_id,
            timestamp=projection.timestamp,
            granularity=projection.granularity,
            source=metadata.source,
            currency=projection.currency,
            cash_value=projection.cash_value,
            portfolio_value=projection.portfolio_value,
            liabilities_value=projection.liabilities_value,
            total_net_worth=projection.net_worth_value,
            is_recalculated=metadata.is_recalculated,
            calculated_at=calculated_at,
            calculation_version=projection.calculation_version,
            created_at=created_at,
            cash_value_by_currency=cash_breakdown,
            portfolio_value_by_currency=portfolio_breakdown,
            liabilities_value_by_currency=liability_breakdown,
            total_net_worth_by_currency=total_breakdown,
            exchange_rates=None,
        )
        return ExpectedNetWorthSnapshotPersistence(snapshot=snapshot, audit=audit)
    except NetWorthSnapshotPersistenceProjectionError:
        raise
    except (InvalidOperation, OverflowError, TypeError, ValueError) as exc:
        raise _fail() from exc
