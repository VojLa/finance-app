"""Pure deterministic planning for coordinated user snapshot refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)

_ERROR_MESSAGE = "Snapshot refresh evidence cannot produce a complete plan."
_TIMESTAMP_PRECISION = 3
_POSTGRES_INTEGER_MAX = 2_147_483_647
_SUPPORTED_ACCOUNT_TYPES = frozenset(
    {
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
)
_REFRESH_ROLES = frozenset(
    {
        AccountMemberRole.owner,
        AccountMemberRole.admin,
        AccountMemberRole.editor,
    }
)


class SnapshotRefreshPlanStateError(ValueError):
    """Raised when user/account evidence cannot produce one complete plan."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


class AccountSnapshotRefreshMode(StrEnum):
    """The operation permitted for one account in a coordinated refresh."""

    refresh = "refresh"
    reuse_only = "reuse_only"


@dataclass(frozen=True, slots=True)
class SnapshotRefreshAccountEvidence:
    """Complete current account and membership evidence for planning."""

    account_id: str
    account_type: AccountType
    account_currency: str
    membership_id: str
    membership_role: AccountMemberRole
    relation_type: AccountRelationType
    accepted_at: datetime
    is_archived: bool
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class SnapshotRefreshPlanInput:
    """Complete typed evidence for one user refresh plan."""

    user_id: str
    user_base_currency: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    accounts: tuple[SnapshotRefreshAccountEvidence, ...]


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotRefreshTarget:
    """Declarative account-snapshot requirement; contains no financial values."""

    account_id: str
    account_type: AccountType
    account_currency: str
    output_currency: str
    requires_fx_conversion: bool
    mode: AccountSnapshotRefreshMode
    membership_role: AccountMemberRole
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool


@dataclass(frozen=True, slots=True)
class ExpectedNetWorthRefreshTarget:
    """Declarative final target that depends on every account target."""

    user_id: str
    output_currency: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    required_account_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpectedUserSnapshotRefreshPlan:
    """Immutable complete account and net-worth refresh dependency plan."""

    user_id: str
    output_currency: str
    account_targets: tuple[ExpectedAccountSnapshotRefreshTarget, ...]
    net_worth_target: ExpectedNetWorthRefreshTarget
    refresh_account_count: int
    reuse_only_account_count: int
    fx_conversion_account_count: int


def _fail() -> SnapshotRefreshPlanStateError:
    return SnapshotRefreshPlanStateError()


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


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % (10 ** (6 - _TIMESTAMP_PRECISION))
    ):
        raise _fail()
    return value


def _aligned_timestamp(
    value: object,
    granularity: SnapshotGranularity,
) -> datetime:
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


def _refresh_mode(value: object) -> AccountSnapshotRefreshMode:
    if not isinstance(value, AccountMemberRole):
        raise _fail()
    if value in _REFRESH_ROLES:
        return AccountSnapshotRefreshMode.refresh
    if value is AccountMemberRole.viewer:
        return AccountSnapshotRefreshMode.reuse_only
    raise _fail()


def _validate_account(
    value: object,
    *,
    output_currency: str,
    snapshot_timestamp: datetime,
    granularity: SnapshotGranularity,
    source: SnapshotSource,
    calculation_version: int,
    calculated_at: datetime,
    created_at: datetime,
    is_recalculated: bool,
) -> tuple[str, str, ExpectedAccountSnapshotRefreshTarget] | None:
    if not isinstance(value, SnapshotRefreshAccountEvidence):
        raise _fail()
    account_id = _nonblank(value.account_id)
    if not isinstance(value.account_type, AccountType):
        raise _fail()
    account_currency = _currency(value.account_currency)
    if not isinstance(value.is_archived, bool):
        raise _fail()
    if value.is_archived:
        if value.archived_at is None:
            raise _fail()
        _timestamp(value.archived_at)
        return None
    if value.archived_at is not None:
        raise _fail()
    if value.account_type not in _SUPPORTED_ACCOUNT_TYPES:
        raise _fail()

    membership_id = _nonblank(value.membership_id)
    mode = _refresh_mode(value.membership_role)
    if not isinstance(value.relation_type, AccountRelationType):
        raise _fail()
    _timestamp(value.accepted_at)

    return (
        account_id,
        membership_id,
        ExpectedAccountSnapshotRefreshTarget(
            account_id=account_id,
            account_type=value.account_type,
            account_currency=account_currency,
            output_currency=output_currency,
            requires_fx_conversion=account_currency != output_currency,
            mode=mode,
            membership_role=value.membership_role,
            snapshot_timestamp=snapshot_timestamp,
            granularity=granularity,
            source=source,
            calculation_version=calculation_version,
            calculated_at=calculated_at,
            created_at=created_at,
            is_recalculated=is_recalculated,
        ),
    )


def build_user_snapshot_refresh_plan(
    value: SnapshotRefreshPlanInput,
) -> ExpectedUserSnapshotRefreshPlan:
    """Build one complete immutable refresh dependency plan without I/O."""

    if not isinstance(value, SnapshotRefreshPlanInput):
        raise _fail()
    user_id = _nonblank(value.user_id)
    output_currency = _currency(value.user_base_currency)
    if not isinstance(value.granularity, SnapshotGranularity):
        raise _fail()
    snapshot_timestamp = _aligned_timestamp(
        value.snapshot_timestamp,
        value.granularity,
    )
    if not isinstance(value.source, SnapshotSource):
        raise _fail()
    calculation_version = _calculation_version(value.calculation_version)
    calculated_at = _timestamp(value.calculated_at)
    created_at = _timestamp(value.created_at)
    if (
        not isinstance(value.is_recalculated, bool)
        or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
        or not isinstance(value.accounts, tuple)
    ):
        raise _fail()

    validated: list[tuple[str, str, ExpectedAccountSnapshotRefreshTarget]] = []
    account_ids: set[str] = set()
    membership_ids: set[str] = set()
    for account in value.accounts:
        result = _validate_account(
            account,
            output_currency=output_currency,
            snapshot_timestamp=snapshot_timestamp,
            granularity=value.granularity,
            source=value.source,
            calculation_version=calculation_version,
            calculated_at=calculated_at,
            created_at=created_at,
            is_recalculated=value.is_recalculated,
        )
        if result is None:
            continue
        account_id, membership_id, target = result
        if account_id in account_ids or membership_id in membership_ids:
            raise _fail()
        account_ids.add(account_id)
        membership_ids.add(membership_id)
        validated.append((account_id, membership_id, target))

    account_targets = tuple(
        item[2] for item in sorted(validated, key=lambda item: (item[0], item[1]))
    )
    required_account_ids = tuple(target.account_id for target in account_targets)
    net_worth_target = ExpectedNetWorthRefreshTarget(
        user_id=user_id,
        output_currency=output_currency,
        snapshot_timestamp=snapshot_timestamp,
        granularity=value.granularity,
        source=value.source,
        calculation_version=calculation_version,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=value.is_recalculated,
        required_account_ids=required_account_ids,
    )
    return ExpectedUserSnapshotRefreshPlan(
        user_id=user_id,
        output_currency=output_currency,
        account_targets=account_targets,
        net_worth_target=net_worth_target,
        refresh_account_count=sum(
            target.mode is AccountSnapshotRefreshMode.refresh for target in account_targets
        ),
        reuse_only_account_count=sum(
            target.mode is AccountSnapshotRefreshMode.reuse_only for target in account_targets
        ),
        fx_conversion_account_count=sum(
            target.requires_fx_conversion for target in account_targets
        ),
    )
