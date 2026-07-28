"""Read-only selection of complete persisted account-snapshot evidence."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import Numeric
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.common import MONEY, QUANTITY, TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotModel
from app.db.models.users import UserModel
from app.modules.net_worth.projection import (
    AccountNetWorthEvidence,
    ExpectedNetWorthProjection,
    NetWorthCurrencyAmount,
    NetWorthProjectionInput,
    NetWorthProjectionStateError,
    build_net_worth_projection,
)
from app.modules.net_worth.repository import (
    NetWorthEvidenceRepository,
    PersistedAccountAccess,
)

_ERROR_MESSAGE = "Persisted evidence cannot produce a complete net worth snapshot."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_SUPPORTED_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}
_COHERENT_ISOLATION_LEVELS = {"repeatable read", "serializable"}


class NetWorthEvidenceStateError(ValueError):
    """Raised when persisted account snapshots are incomplete, ambiguous, or corrupt."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class BuildNetWorthEvidenceCommand:
    user_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int


@dataclass(frozen=True, slots=True)
class SelectedAccountSnapshotIdentity:
    account_id: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class CompleteNetWorthEvidence:
    projection: ExpectedNetWorthProjection
    selected_account_ids: tuple[str, ...]
    selected_account_snapshot_ids: tuple[str, ...]
    selected_identities: tuple[SelectedAccountSnapshotIdentity, ...]


type ProjectionBuilder = Callable[[NetWorthProjectionInput], ExpectedNetWorthProjection]


def _fail() -> NetWorthEvidenceStateError:
    return NetWorthEvidenceStateError()


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


def _calculation_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _exact(value: object, numeric: Numeric, *, nonnegative: bool = False) -> Decimal:
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


def _canonical_json_decimal(value: object, numeric: Numeric) -> Decimal:
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None or not isinstance(value, str):
        raise _fail()
    pattern = rf"-?(?:0|[1-9]\d*)\.\d{{{scale}}}"
    if re.fullmatch(pattern, value, flags=re.ASCII) is None:
        raise _fail()
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _fail() from exc
    return _exact(parsed, numeric)


def _parse_breakdown(
    value: object,
    *,
    numeric: Numeric,
) -> tuple[NetWorthCurrencyAmount, ...] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _fail()
    amounts: dict[str, Decimal] = {}
    for raw_currency, raw_amount in value.items():
        currency = _currency(raw_currency)
        if currency in amounts:
            raise _fail()
        amounts[currency] = _canonical_json_decimal(raw_amount, numeric)
    return tuple(
        NetWorthCurrencyAmount(currency=currency, amount=amounts[currency])
        for currency in sorted(amounts)
    )


def _validate_command(command: object) -> BuildNetWorthEvidenceCommand:
    if not isinstance(command, BuildNetWorthEvidenceCommand):
        raise _fail()
    user_id = _nonblank(command.user_id)
    if not isinstance(command.granularity, SnapshotGranularity):
        raise _fail()
    timestamp = _aligned_timestamp(command.timestamp, command.granularity)
    currency = _currency(command.currency)
    calculation_version = _calculation_version(command.calculation_version)
    return BuildNetWorthEvidenceCommand(
        user_id=user_id,
        timestamp=timestamp,
        granularity=command.granularity,
        currency=currency,
        calculation_version=calculation_version,
    )


def _active_accounts(
    accesses: tuple[PersistedAccountAccess, ...],
    *,
    user_id: str,
) -> tuple[AccountModel, ...]:
    accounts: list[AccountModel] = []
    account_ids: set[str] = set()
    membership_ids: set[str] = set()
    for access in accesses:
        if not isinstance(access, PersistedAccountAccess):
            raise _fail()
        account = access.account
        membership = access.membership
        if not isinstance(account, AccountModel) or not isinstance(
            membership,
            AccountMemberModel,
        ):
            raise _fail()
        account_id = _nonblank(account.id)
        membership_id = _nonblank(membership.id)
        if (
            account_id in account_ids
            or membership_id in membership_ids
            or membership.user_id != user_id
            or membership.account_id != account_id
            or not isinstance(membership.role, AccountMemberRole)
            or not isinstance(membership.relation_type, AccountRelationType)
            or membership.accepted_at is None
        ):
            raise _fail()
        _timestamp(membership.accepted_at)
        account_ids.add(account_id)
        membership_ids.add(membership_id)

        if not isinstance(account.is_archived, bool):
            raise _fail()
        if account.is_archived:
            if account.archived_at is None:
                raise _fail()
            _timestamp(account.archived_at)
            continue
        if account.archived_at is not None:
            raise _fail()
        if not isinstance(account.type, AccountType):
            raise _fail()
        _currency(account.currency)
        if account.type not in _SUPPORTED_ACCOUNT_TYPES:
            raise _fail()
        accounts.append(account)
    return tuple(sorted(accounts, key=lambda account: account.id))


def _validate_snapshot_financial_fields(
    snapshot: AccountSnapshotModel,
) -> tuple[
    tuple[NetWorthCurrencyAmount, ...] | None,
    tuple[NetWorthCurrencyAmount, ...] | None,
]:
    cash_value = _exact(snapshot.cash_value, MONEY)
    investment_value = _exact(snapshot.investment_value, MONEY, nonnegative=True)
    investment_cost_basis = _exact(
        snapshot.investment_cost_basis,
        MONEY,
        nonnegative=True,
    )
    _exact(snapshot.liabilities_value, MONEY, nonnegative=True)
    _exact(snapshot.total_value, MONEY)
    _exact(snapshot.net_deposits_value, MONEY)
    _exact(snapshot.realized_pnl_value, MONEY)
    unrealized_pnl = _exact(snapshot.unrealized_pnl_value, MONEY)
    _exact(snapshot.fees_value, MONEY, nonnegative=True)
    _exact(snapshot.taxes_value, MONEY, nonnegative=True)
    if investment_value - investment_cost_basis != unrealized_pnl:
        raise _fail()

    cash = _parse_breakdown(snapshot.cash_value_by_currency, numeric=MONEY)
    investment = _parse_breakdown(
        snapshot.investment_value_by_currency,
        numeric=QUANTITY,
    )
    _parse_breakdown(snapshot.investment_cost_basis_by_currency, numeric=QUANTITY)
    _parse_breakdown(snapshot.net_deposits_by_currency, numeric=MONEY)
    _parse_breakdown(snapshot.realized_pnl_by_currency, numeric=MONEY)
    _parse_breakdown(snapshot.unrealized_pnl_by_currency, numeric=MONEY)
    _parse_breakdown(snapshot.fees_by_currency, numeric=MONEY)
    _parse_breakdown(snapshot.taxes_by_currency, numeric=MONEY)
    if snapshot.exchange_rates is not None and not isinstance(snapshot.exchange_rates, dict):
        raise _fail()

    if cash is not None and not cash and cash_value != 0:
        raise _fail()
    if investment is not None and not investment and investment_value != 0:
        raise _fail()
    return cash, investment


def _snapshot_evidence(
    snapshot: AccountSnapshotModel,
    *,
    account: AccountModel,
    command: BuildNetWorthEvidenceCommand,
) -> AccountNetWorthEvidence:
    if (
        not isinstance(snapshot, AccountSnapshotModel)
        or _nonblank(snapshot.account_id) != account.id
        or _timestamp(snapshot.timestamp) != command.timestamp
        or not isinstance(snapshot.granularity, SnapshotGranularity)
        or snapshot.granularity is not command.granularity
        or _currency(snapshot.currency) != command.currency
        or not isinstance(snapshot.source, SnapshotSource)
        or not isinstance(snapshot.is_recalculated, bool)
        or _calculation_version(snapshot.calculation_version) != command.calculation_version
    ):
        raise _fail()
    snapshot_id = _nonblank(snapshot.id)
    _timestamp(snapshot.calculated_at)
    _timestamp(snapshot.created_at)
    cash_breakdown, investment_breakdown = _validate_snapshot_financial_fields(snapshot)
    return AccountNetWorthEvidence(
        snapshot_id=snapshot_id,
        account_id=account.id,
        account_type=account.type,
        account_currency=account.currency,
        snapshot_currency=snapshot.currency,
        timestamp=snapshot.timestamp,
        granularity=snapshot.granularity,
        total_value=snapshot.total_value,
        cash_value=snapshot.cash_value,
        investment_value=snapshot.investment_value,
        liabilities_value=snapshot.liabilities_value,
        cash_value_by_currency=cash_breakdown,
        investment_value_by_currency=investment_breakdown,
        liabilities_value_by_currency=None,
    )


class NetWorthEvidenceService:
    """Build complete immutable evidence inside a coherent caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: NetWorthEvidenceRepository | None = None,
        projection_builder: ProjectionBuilder = build_net_worth_projection,
    ) -> None:
        self.session = session
        self.repository = repository or NetWorthEvidenceRepository(session)
        self.projection_builder = projection_builder

    async def build(self, command: BuildNetWorthEvidenceCommand) -> CompleteNetWorthEvidence:
        try:
            canonical = _validate_command(command)
            if not self.session.in_transaction():
                raise _fail()
            isolation = await self.repository.load_transaction_isolation()
            if (
                not isinstance(isolation, str)
                or isolation.replace("_", " ").lower() not in _COHERENT_ISOLATION_LEVELS
            ):
                raise _fail()

            user = await self.repository.load_user(canonical.user_id)
            if (
                user is None
                or not isinstance(user, UserModel)
                or _nonblank(user.id) != canonical.user_id
            ):
                raise _fail()
            accesses = await self.repository.load_account_accesses(canonical.user_id)
            accounts = _active_accounts(accesses, user_id=canonical.user_id)
            account_ids = tuple(account.id for account in accounts)
            snapshots = (
                await self.repository.load_exact_snapshots(
                    account_ids=account_ids,
                    timestamp=canonical.timestamp,
                    granularity=canonical.granularity,
                    currency=canonical.currency,
                )
                if account_ids
                else ()
            )

            snapshots_by_account: dict[str, list[AccountSnapshotModel]] = {}
            snapshot_ids: set[str] = set()
            for snapshot in snapshots:
                if not isinstance(snapshot, AccountSnapshotModel):
                    raise _fail()
                account_id = _nonblank(snapshot.account_id)
                snapshot_id = _nonblank(snapshot.id)
                if account_id not in set(account_ids) or snapshot_id in snapshot_ids:
                    raise _fail()
                snapshot_ids.add(snapshot_id)
                snapshots_by_account.setdefault(account_id, []).append(snapshot)

            mapped: list[AccountNetWorthEvidence] = []
            identities: list[SelectedAccountSnapshotIdentity] = []
            for account in accounts:
                candidates = snapshots_by_account.get(account.id, [])
                if len(candidates) != 1:
                    raise _fail()
                evidence = _snapshot_evidence(
                    candidates[0],
                    account=account,
                    command=canonical,
                )
                mapped.append(evidence)
                identities.append(
                    SelectedAccountSnapshotIdentity(
                        account_id=evidence.account_id,
                        snapshot_id=evidence.snapshot_id,
                    )
                )
            if set(snapshots_by_account) != set(account_ids):
                raise _fail()

            projection_input = NetWorthProjectionInput(
                user_id=canonical.user_id,
                timestamp=canonical.timestamp,
                granularity=canonical.granularity,
                currency=canonical.currency,
                calculation_version=canonical.calculation_version,
                account_snapshots=tuple(mapped),
            )
            projection = self.projection_builder(projection_input)
            if not isinstance(projection, ExpectedNetWorthProjection):
                raise _fail()
            ordered_identities = tuple(
                sorted(
                    identities,
                    key=lambda identity: (identity.account_id, identity.snapshot_id),
                )
            )
            return CompleteNetWorthEvidence(
                projection=projection,
                selected_account_ids=tuple(identity.account_id for identity in ordered_identities),
                selected_account_snapshot_ids=tuple(
                    identity.snapshot_id for identity in ordered_identities
                ),
                selected_identities=ordered_identities,
            )
        except NetWorthEvidenceStateError:
            raise
        except NetWorthProjectionStateError as exc:
            raise _fail() from exc
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise _fail() from exc
