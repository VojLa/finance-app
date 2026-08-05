"""Authenticated orchestration for coordinated manual snapshot refresh."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshResult,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode
from app.modules.snapshot_refresh.version import (
    current_coordinated_snapshot_calculation_version,
)
from app.modules.snapshots.manual_service import (
    CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION,
)
from app.shared.errors import ApplicationError

MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY = SnapshotGranularity.minute
MANUAL_USER_SNAPSHOT_REFRESH_SOURCE = SnapshotSource.manual_recalculation
CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION = CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION
_POSTGRES_INTEGER_MAX = 2_147_483_647
Clock = Callable[[], datetime]


class UserSnapshotRefreshUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="snapshot_refresh_unavailable",
            message="Snapshot refresh cannot be completed from the current account data.",
            status_code=409,
        )


class UserSnapshotRefreshConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="snapshot_refresh_conflict",
            message="Snapshot refresh conflicts with existing data.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class RecalculateUserSnapshotRefreshCommand:
    principal: AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class SnapshotRefreshAccountSelection:
    account_id: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class RecalculateUserSnapshotRefreshResult:
    net_worth_snapshot_id: str
    net_worth_status: Literal["created", "replayed"]
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    accounts: tuple[SnapshotRefreshAccountSelection, ...]
    refresh_account_count: int
    reuse_only_account_count: int
    created_account_snapshot_count: int
    replayed_account_snapshot_count: int
    reused_account_snapshot_count: int
    selected_account_snapshot_count: int


class _MarketBackedRefreshService(Protocol):
    async def execute(
        self,
        command: ExecuteMarketBackedSnapshotRefreshCommand,
    ) -> ExecuteMarketBackedSnapshotRefreshResult: ...


def current_user_snapshot_refresh_timestamp() -> datetime:
    return datetime.now(UTC)


def canonical_manual_user_snapshot_refresh_bucket(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise UserSnapshotRefreshUnavailableError()
    normalized = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return normalized.replace(second=0, microsecond=0)


def _principal(value: object) -> AuthenticatedPrincipal:
    if not isinstance(value, RecalculateUserSnapshotRefreshCommand):
        raise UserSnapshotRefreshUnavailableError()
    principal = value.principal
    if (
        not isinstance(principal, AuthenticatedPrincipal)
        or not isinstance(principal.user_id, str)
        or not principal.user_id
        or principal.user_id != principal.user_id.strip()
    ):
        raise UserSnapshotRefreshUnavailableError()
    return principal


def _calculation_version() -> int:
    try:
        version = current_coordinated_snapshot_calculation_version()
    except ValueError as exc:
        raise UserSnapshotRefreshUnavailableError() from exc
    if version != CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION:
        raise UserSnapshotRefreshUnavailableError()
    return version


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise UserSnapshotRefreshUnavailableError()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise UserSnapshotRefreshUnavailableError()
    return currency


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise UserSnapshotRefreshUnavailableError()
    return value


def _version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 < value <= _POSTGRES_INTEGER_MAX
    ):
        raise UserSnapshotRefreshUnavailableError()
    return value


def _validated_account_executions(
    value: object,
) -> tuple[ExecutedAccountSnapshotRefresh, ...]:
    if not isinstance(value, tuple):
        raise UserSnapshotRefreshUnavailableError()
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    validated: list[ExecutedAccountSnapshotRefresh] = []
    for execution in value:
        if not isinstance(execution, ExecutedAccountSnapshotRefresh):
            raise UserSnapshotRefreshUnavailableError()
        account_id = _nonblank(execution.account_id)
        snapshot_id = _nonblank(execution.snapshot_id)
        if (
            account_id in account_ids
            or snapshot_id in snapshot_ids
            or not isinstance(execution.mode, AccountSnapshotRefreshMode)
            or not isinstance(
                execution.disposition,
                AccountSnapshotRefreshExecutionDisposition,
            )
            or (
                execution.mode is AccountSnapshotRefreshMode.refresh
                and execution.disposition
                not in {
                    AccountSnapshotRefreshExecutionDisposition.created,
                    AccountSnapshotRefreshExecutionDisposition.replayed,
                }
            )
            or (
                execution.mode is AccountSnapshotRefreshMode.reuse_only
                and execution.disposition is not AccountSnapshotRefreshExecutionDisposition.reused
            )
        ):
            raise UserSnapshotRefreshUnavailableError()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        validated.append(execution)
    return tuple(validated)


def _validated_lineage(
    value: object,
    executions: tuple[ExecutedAccountSnapshotRefresh, ...],
) -> tuple[SelectedAccountSnapshotIdentity, ...]:
    if not isinstance(value, tuple):
        raise UserSnapshotRefreshUnavailableError()
    expected = tuple(
        SelectedAccountSnapshotIdentity(
            account_id=execution.account_id,
            snapshot_id=execution.snapshot_id,
        )
        for execution in executions
    )
    if (
        value != expected
        or any(not isinstance(identity, SelectedAccountSnapshotIdentity) for identity in value)
        or value
        != tuple(
            sorted(
                value,
                key=lambda identity: (
                    identity.account_id,
                    identity.snapshot_id,
                ),
            )
        )
    ):
        raise UserSnapshotRefreshUnavailableError()
    return value


def _manifest(
    lineage: object,
    *,
    executions: tuple[ExecutedAccountSnapshotRefresh, ...],
    selected_count: int,
) -> tuple[SnapshotRefreshAccountSelection, ...]:
    if not isinstance(lineage, tuple):
        raise UserSnapshotRefreshUnavailableError()
    accounts: list[SnapshotRefreshAccountSelection] = []
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    for identity in lineage:
        if not isinstance(identity, SelectedAccountSnapshotIdentity):
            raise UserSnapshotRefreshUnavailableError()
        account_id = _nonblank(identity.account_id)
        snapshot_id = _nonblank(identity.snapshot_id)
        if account_id in account_ids or snapshot_id in snapshot_ids:
            raise UserSnapshotRefreshUnavailableError()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        accounts.append(
            SnapshotRefreshAccountSelection(
                account_id=account_id,
                snapshot_id=snapshot_id,
            )
        )
    result = tuple(accounts)
    if (
        len(result) != selected_count
        or len(result) != len(executions)
        or tuple(item.account_id for item in result)
        != tuple(execution.account_id for execution in executions)
        or tuple(item.snapshot_id for item in result)
        != tuple(execution.snapshot_id for execution in executions)
    ):
        raise UserSnapshotRefreshUnavailableError()
    return result


def _validate_executor_result(
    value: object,
    *,
    principal: AuthenticatedPrincipal,
    bucket: datetime,
    calculation_version: int,
) -> ExecuteUserSnapshotRefreshResult:
    if not isinstance(value, ExecuteUserSnapshotRefreshResult):
        raise UserSnapshotRefreshUnavailableError()
    executions = _validated_account_executions(value.account_snapshots)
    lineage = _validated_lineage(
        value.required_account_snapshot_identities,
        executions,
    )
    refresh_count = _count(value.refresh_account_count)
    reuse_count = _count(value.reuse_only_account_count)
    created_count = _count(value.created_account_snapshot_count)
    replayed_count = _count(value.replayed_account_snapshot_count)
    reused_count = _count(value.reused_account_snapshot_count)
    selected_count = _count(value.selected_account_snapshot_count)
    if (
        value.user_id != principal.user_id
        or value.snapshot_timestamp != bucket
        or value.granularity is not MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY
        or value.source is not MANUAL_USER_SNAPSHOT_REFRESH_SOURCE
        or _version(value.calculation_version) != calculation_version
        or not isinstance(value.net_worth_disposition, NetWorthSnapshotWriteDisposition)
        or refresh_count != created_count + replayed_count
        or reuse_count != reused_count
        or selected_count != refresh_count + reuse_count
        or len(executions) != selected_count
        or len(lineage) != selected_count
        or created_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.created
            for item in executions
        )
        or replayed_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.replayed
            for item in executions
        )
        or reused_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.reused
            for item in executions
        )
    ):
        raise UserSnapshotRefreshUnavailableError()
    _currency(value.output_currency)
    _nonblank(value.net_worth_snapshot_id)
    return value


class ManualUserSnapshotRefreshService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        market_backed_service: _MarketBackedRefreshService,
        clock: Clock = current_user_snapshot_refresh_timestamp,
    ) -> None:
        self.session = session
        self.market_backed_service = market_backed_service
        self.clock = clock

    async def recalculate(
        self,
        command: RecalculateUserSnapshotRefreshCommand,
    ) -> RecalculateUserSnapshotRefreshResult:
        try:
            principal = _principal(command)
            calculation_version = _calculation_version()
        except UserSnapshotRefreshUnavailableError:
            await self._close_active_transaction()
            raise

        try:
            await self.session.commit()
        except Exception:
            await self._close_active_transaction()
            raise
        await self._require_idle(
            "Market-backed snapshot refresh requires an idle database session."
        )

        bucket = canonical_manual_user_snapshot_refresh_bucket(self.clock())
        market_backed_command = ExecuteMarketBackedSnapshotRefreshCommand(
            user_id=principal.user_id,
            snapshot_timestamp=bucket,
            granularity=MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY,
            source=MANUAL_USER_SNAPSHOT_REFRESH_SOURCE,
            calculation_version=calculation_version,
            calculated_at=bucket,
            created_at=bucket,
            is_recalculated=True,
        )
        try:
            market_backed_result = await self.market_backed_service.execute(market_backed_command)
        except MarketBackedSnapshotRefreshConflictError as exc:
            await self._require_idle(
                "Market-backed snapshot refresh left an active database transaction."
            )
            raise UserSnapshotRefreshConflictError() from exc
        except MarketBackedSnapshotRefreshUnavailableError as exc:
            await self._require_idle(
                "Market-backed snapshot refresh left an active database transaction."
            )
            raise UserSnapshotRefreshUnavailableError() from exc
        except Exception:
            await self._require_idle(
                "Market-backed snapshot refresh left an active database transaction."
            )
            raise
        await self._require_idle(
            "Market-backed snapshot refresh left an active database transaction."
        )
        if not isinstance(
            market_backed_result,
            ExecuteMarketBackedSnapshotRefreshResult,
        ):
            raise UserSnapshotRefreshUnavailableError()
        result = _validate_executor_result(
            market_backed_result.snapshots,
            principal=principal,
            bucket=bucket,
            calculation_version=calculation_version,
        )
        accounts = _manifest(
            result.required_account_snapshot_identities,
            executions=result.account_snapshots,
            selected_count=result.selected_account_snapshot_count,
        )
        return RecalculateUserSnapshotRefreshResult(
            net_worth_snapshot_id=result.net_worth_snapshot_id,
            net_worth_status=result.net_worth_disposition.value,
            timestamp=result.snapshot_timestamp,
            granularity=result.granularity,
            currency=result.output_currency,
            calculation_version=result.calculation_version,
            accounts=accounts,
            refresh_account_count=result.refresh_account_count,
            reuse_only_account_count=result.reuse_only_account_count,
            created_account_snapshot_count=result.created_account_snapshot_count,
            replayed_account_snapshot_count=result.replayed_account_snapshot_count,
            reused_account_snapshot_count=result.reused_account_snapshot_count,
            selected_account_snapshot_count=result.selected_account_snapshot_count,
        )

    async def _require_idle(self, message: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(message)

    async def _close_active_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
