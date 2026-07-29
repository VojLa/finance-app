"""Read-only persisted evidence selection for complete snapshot-refresh coverage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotModel
from app.db.models.users import UserModel
from app.modules.snapshot_refresh.plan import (
    AccountSnapshotRefreshMode,
    ExpectedAccountSnapshotRefreshTarget,
    ExpectedUserSnapshotRefreshPlan,
    SnapshotRefreshAccountEvidence,
    SnapshotRefreshPlanInput,
    SnapshotRefreshPlanStateError,
    build_user_snapshot_refresh_plan,
)
from app.modules.snapshot_refresh.repository import (
    PersistedSnapshotRefreshAccess,
    SnapshotRefreshEvidenceRepository,
)

_ERROR_MESSAGE = "Persisted evidence cannot produce complete snapshot refresh coverage."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_COHERENT_ISOLATION_LEVELS = frozenset({"repeatable read", "serializable"})


class SnapshotRefreshEvidenceStateError(ValueError):
    """Raised when persisted rows cannot prove complete refresh coverage."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class BuildSnapshotRefreshCoverageCommand:
    """Server-owned metadata for persisted refresh-target discovery."""

    user_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool


@dataclass(frozen=True, slots=True)
class SelectedReusableAccountSnapshot:
    """Minimal immutable identity of one selected reusable snapshot."""

    account_id: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class CompleteSnapshotRefreshCoverage:
    """Complete immutable refresh/reuse partition and reuse audit."""

    plan: ExpectedUserSnapshotRefreshPlan
    refresh_targets: tuple[ExpectedAccountSnapshotRefreshTarget, ...]
    reuse_only_targets: tuple[ExpectedAccountSnapshotRefreshTarget, ...]
    selected_reuse_snapshots: tuple[SelectedReusableAccountSnapshot, ...]
    refresh_target_count: int
    reuse_only_target_count: int
    selected_reuse_snapshot_count: int


type RefreshPlanBuilder = Callable[
    [SnapshotRefreshPlanInput],
    ExpectedUserSnapshotRefreshPlan,
]


def _fail() -> SnapshotRefreshEvidenceStateError:
    return SnapshotRefreshEvidenceStateError()


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


def _validate_command(
    value: object,
) -> BuildSnapshotRefreshCoverageCommand:
    if not isinstance(value, BuildSnapshotRefreshCoverageCommand):
        raise _fail()
    user_id = _nonblank(value.user_id)
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
    if not isinstance(value.is_recalculated, bool) or value.is_recalculated is not (
        value.source is SnapshotSource.manual_recalculation
    ):
        raise _fail()
    return BuildSnapshotRefreshCoverageCommand(
        user_id=user_id,
        snapshot_timestamp=snapshot_timestamp,
        granularity=value.granularity,
        source=value.source,
        calculation_version=calculation_version,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=value.is_recalculated,
    )


def _persisted_user(value: object, *, user_id: str) -> UserModel:
    if not isinstance(value, UserModel) or _nonblank(value.id) != user_id:
        raise _fail()
    _currency(value.base_currency)
    return value


def _account_evidence(
    values: object,
    *,
    user_id: str,
) -> tuple[SnapshotRefreshAccountEvidence, ...]:
    if not isinstance(values, tuple):
        raise _fail()
    mapped: list[SnapshotRefreshAccountEvidence] = []
    account_ids: set[str] = set()
    membership_ids: set[str] = set()
    for value in values:
        if not isinstance(value, PersistedSnapshotRefreshAccess):
            raise _fail()
        account = value.account
        membership = value.membership
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
            or membership.account_id != account_id
            or membership.user_id != user_id
            or not isinstance(account.type, AccountType)
            or not isinstance(account.is_archived, bool)
            or not isinstance(membership.role, AccountMemberRole)
            or not isinstance(membership.relation_type, AccountRelationType)
            or membership.accepted_at is None
        ):
            raise _fail()
        account_ids.add(account_id)
        membership_ids.add(membership_id)
        account_currency = _currency(account.currency)
        accepted_at = _timestamp(membership.accepted_at)
        archived_at = _timestamp(account.archived_at) if account.archived_at is not None else None
        mapped.append(
            SnapshotRefreshAccountEvidence(
                account_id=account_id,
                account_type=account.type,
                account_currency=account_currency,
                membership_id=membership_id,
                membership_role=membership.role,
                relation_type=membership.relation_type,
                accepted_at=accepted_at,
                is_archived=account.is_archived,
                archived_at=archived_at,
            )
        )
    return tuple(mapped)


def _partition(
    plan: ExpectedUserSnapshotRefreshPlan,
) -> tuple[
    tuple[ExpectedAccountSnapshotRefreshTarget, ...],
    tuple[ExpectedAccountSnapshotRefreshTarget, ...],
]:
    refresh_targets = tuple(
        target
        for target in plan.account_targets
        if target.mode is AccountSnapshotRefreshMode.refresh
    )
    reuse_only_targets = tuple(
        target
        for target in plan.account_targets
        if target.mode is AccountSnapshotRefreshMode.reuse_only
    )
    if (
        len(refresh_targets) != plan.refresh_account_count
        or len(reuse_only_targets) != plan.reuse_only_account_count
        or {target.account_id for target in refresh_targets}
        & {target.account_id for target in reuse_only_targets}
        or {target.account_id for target in refresh_targets}
        | {target.account_id for target in reuse_only_targets}
        != {target.account_id for target in plan.account_targets}
    ):
        raise _fail()
    return refresh_targets, reuse_only_targets


def _selected_reuse_snapshots(
    values: object,
    *,
    targets: tuple[ExpectedAccountSnapshotRefreshTarget, ...],
    calculation_version: int,
) -> tuple[SelectedReusableAccountSnapshot, ...]:
    if not isinstance(values, tuple):
        raise _fail()
    target_by_account = {target.account_id: target for target in targets}
    candidates: dict[str, AccountSnapshotModel] = {}
    snapshot_ids: set[str] = set()
    for value in values:
        if not isinstance(value, AccountSnapshotModel):
            raise _fail()
        account_id = _nonblank(value.account_id)
        snapshot_id = _nonblank(value.id)
        target = target_by_account.get(account_id)
        if (
            target is None
            or account_id in candidates
            or snapshot_id in snapshot_ids
            or _timestamp(value.timestamp) != target.snapshot_timestamp
            or not isinstance(value.granularity, SnapshotGranularity)
            or value.granularity is not target.granularity
            or _currency(value.currency) != target.output_currency
            or _calculation_version(value.calculation_version) != calculation_version
            or not isinstance(value.source, SnapshotSource)
            or not isinstance(value.is_recalculated, bool)
            or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
        ):
            raise _fail()
        _timestamp(value.calculated_at)
        _timestamp(value.created_at)
        candidates[account_id] = value
        snapshot_ids.add(snapshot_id)

    if set(candidates) != set(target_by_account):
        raise _fail()
    return tuple(
        SelectedReusableAccountSnapshot(
            account_id=target.account_id,
            snapshot_id=candidates[target.account_id].id,
        )
        for target in targets
    )


class SnapshotRefreshEvidenceService:
    """Build persisted refresh coverage inside a coherent caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SnapshotRefreshEvidenceRepository | None = None,
        plan_builder: RefreshPlanBuilder = build_user_snapshot_refresh_plan,
    ) -> None:
        self.session = session
        self.repository = repository or SnapshotRefreshEvidenceRepository(session)
        self.plan_builder = plan_builder

    async def build(
        self,
        command: BuildSnapshotRefreshCoverageCommand,
    ) -> CompleteSnapshotRefreshCoverage:
        canonical = _validate_command(command)
        if not self.session.in_transaction():
            raise _fail()
        isolation = await self.repository.load_transaction_isolation()
        if (
            not isinstance(isolation, str)
            or isolation.replace("_", " ").lower() not in _COHERENT_ISOLATION_LEVELS
        ):
            raise _fail()

        user = _persisted_user(
            await self.repository.load_user(canonical.user_id),
            user_id=canonical.user_id,
        )
        account_evidence = _account_evidence(
            await self.repository.load_account_accesses(canonical.user_id),
            user_id=canonical.user_id,
        )
        plan_input = SnapshotRefreshPlanInput(
            user_id=user.id,
            user_base_currency=user.base_currency,
            snapshot_timestamp=canonical.snapshot_timestamp,
            granularity=canonical.granularity,
            source=canonical.source,
            calculation_version=canonical.calculation_version,
            calculated_at=canonical.calculated_at,
            created_at=canonical.created_at,
            is_recalculated=canonical.is_recalculated,
            accounts=account_evidence,
        )
        try:
            plan = self.plan_builder(plan_input)
        except SnapshotRefreshPlanStateError as exc:
            raise _fail() from exc
        if not isinstance(plan, ExpectedUserSnapshotRefreshPlan):
            raise _fail()
        refresh_targets, reuse_only_targets = _partition(plan)
        reuse_ids = tuple(target.account_id for target in reuse_only_targets)
        snapshots = (
            await self.repository.load_exact_reuse_snapshots(
                account_ids=reuse_ids,
                timestamp=plan.net_worth_target.snapshot_timestamp,
                granularity=plan.net_worth_target.granularity,
                currency=plan.output_currency,
            )
            if reuse_ids
            else ()
        )
        selected = _selected_reuse_snapshots(
            snapshots,
            targets=reuse_only_targets,
            calculation_version=plan.net_worth_target.calculation_version,
        )
        if tuple(target.account_id for target in reuse_only_targets) != tuple(
            identity.account_id for identity in selected
        ):
            raise _fail()
        return CompleteSnapshotRefreshCoverage(
            plan=plan,
            refresh_targets=refresh_targets,
            reuse_only_targets=reuse_only_targets,
            selected_reuse_snapshots=selected,
            refresh_target_count=len(refresh_targets),
            reuse_only_target_count=len(reuse_only_targets),
            selected_reuse_snapshot_count=len(selected),
        )
