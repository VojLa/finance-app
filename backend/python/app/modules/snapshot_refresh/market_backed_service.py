"""Coordinate production market evidence before exact user snapshot refresh."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.common import TIMESTAMP
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import (
    MarketEvidenceConflictError,
    MarketEvidenceRefreshResult,
    MarketEvidenceStateError,
)
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode

_POSTGRES_INTEGER_MAX = 2_147_483_647


class _MarketService(Protocol):
    async def refresh(
        self,
        command: RefreshMarketEvidenceCommand,
    ) -> MarketEvidenceRefreshResult: ...


class _SnapshotExecutor(Protocol):
    async def execute(
        self,
        command: ExecuteUserSnapshotRefreshCommand,
    ) -> ExecuteUserSnapshotRefreshResult: ...


type MarketServiceFactory = Callable[[AsyncSession, Settings], _MarketService]
type SnapshotExecutorFactory = Callable[[AsyncSession], _SnapshotExecutor]


def _unavailable() -> MarketBackedSnapshotRefreshUnavailableError:
    return MarketBackedSnapshotRefreshUnavailableError()


def _conflict() -> MarketBackedSnapshotRefreshConflictError:
    return MarketBackedSnapshotRefreshConflictError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _unavailable()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise _unavailable()
    return currency


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision != 3
        or value.microsecond % 1_000 != 0
    ):
        raise _unavailable()
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
        raise _unavailable()
    if not aligned:
        raise _unavailable()
    return timestamp


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _unavailable()
    return value


def _calculation_version(value: object) -> int:
    version = _count(value)
    if not 1 <= version <= _POSTGRES_INTEGER_MAX:
        raise _unavailable()
    return version


def _validate_command(
    value: object,
) -> ExecuteMarketBackedSnapshotRefreshCommand:
    if not isinstance(value, ExecuteMarketBackedSnapshotRefreshCommand):
        raise _unavailable()
    if (
        not isinstance(value.granularity, SnapshotGranularity)
        or not isinstance(value.source, SnapshotSource)
        or not isinstance(value.is_recalculated, bool)
        or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
    ):
        raise _unavailable()
    _nonblank(value.user_id)
    _aligned_timestamp(value.snapshot_timestamp, value.granularity)
    _calculation_version(value.calculation_version)
    _timestamp(value.calculated_at)
    _timestamp(value.created_at)
    return value


def _canonical_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise _unavailable()
    ids = tuple(_nonblank(item) for item in value)
    if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
        raise _unavailable()
    return ids


def _validate_market_result(
    value: object,
    command: ExecuteMarketBackedSnapshotRefreshCommand,
) -> MarketEvidenceRefreshResult:
    if (
        not isinstance(value, MarketEvidenceRefreshResult)
        or value.user_id != command.user_id
        or value.snapshot_timestamp != command.snapshot_timestamp
    ):
        raise _unavailable()
    _currency(value.output_currency)
    required_price_count = _count(value.required_price_count)
    required_fx_count = _count(value.required_fx_count)
    price_ids = _canonical_ids(value.price_ids)
    exchange_rate_ids = _canonical_ids(value.exchange_rate_ids)
    prices_created = _count(value.prices_created)
    prices_replayed = _count(value.prices_replayed)
    rates_created = _count(value.rates_created)
    rates_replayed = _count(value.rates_replayed)
    if (
        prices_created + prices_replayed != len(price_ids)
        or rates_created + rates_replayed != len(exchange_rate_ids)
        or len(price_ids) > required_price_count
        or len(exchange_rate_ids) > required_fx_count
        or (required_price_count == 0 and price_ids)
        or (required_fx_count == 0 and exchange_rate_ids)
    ):
        raise _unavailable()
    return value


def _validate_execution(
    value: object,
    *,
    command: ExecuteMarketBackedSnapshotRefreshCommand,
    output_currency: str,
) -> ExecuteUserSnapshotRefreshResult:
    if (
        not isinstance(value, ExecuteUserSnapshotRefreshResult)
        or value.user_id != command.user_id
        or value.snapshot_timestamp != command.snapshot_timestamp
        or value.granularity is not command.granularity
        or value.output_currency != output_currency
        or value.source is not command.source
        or value.calculation_version != command.calculation_version
        or not isinstance(value.account_snapshots, tuple)
        or not isinstance(value.required_account_snapshot_identities, tuple)
        or not isinstance(value.net_worth_disposition, NetWorthSnapshotWriteDisposition)
    ):
        raise _unavailable()
    _currency(value.output_currency)
    _nonblank(value.net_worth_snapshot_id)

    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    executions: list[ExecutedAccountSnapshotRefresh] = []
    for execution in value.account_snapshots:
        if not isinstance(execution, ExecutedAccountSnapshotRefresh):
            raise _unavailable()
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
            raise _unavailable()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        executions.append(execution)
    canonical_executions = tuple(executions)
    if canonical_executions != tuple(
        sorted(
            canonical_executions,
            key=lambda item: (item.account_id, item.snapshot_id),
        )
    ):
        raise _unavailable()

    identities: list[SelectedAccountSnapshotIdentity] = []
    identity_accounts: set[str] = set()
    identity_snapshots: set[str] = set()
    for identity in value.required_account_snapshot_identities:
        if not isinstance(identity, SelectedAccountSnapshotIdentity):
            raise _unavailable()
        account_id = _nonblank(identity.account_id)
        snapshot_id = _nonblank(identity.snapshot_id)
        if account_id in identity_accounts or snapshot_id in identity_snapshots:
            raise _unavailable()
        identity_accounts.add(account_id)
        identity_snapshots.add(snapshot_id)
        identities.append(identity)
    canonical_identities = tuple(identities)
    expected_identities = tuple(
        SelectedAccountSnapshotIdentity(
            account_id=execution.account_id,
            snapshot_id=execution.snapshot_id,
        )
        for execution in canonical_executions
    )
    if canonical_identities != expected_identities or canonical_identities != tuple(
        sorted(
            canonical_identities,
            key=lambda item: (item.account_id, item.snapshot_id),
        )
    ):
        raise _unavailable()

    refresh_count = sum(
        item.mode is AccountSnapshotRefreshMode.refresh for item in canonical_executions
    )
    reuse_count = sum(
        item.mode is AccountSnapshotRefreshMode.reuse_only for item in canonical_executions
    )
    created_count = sum(
        item.disposition is AccountSnapshotRefreshExecutionDisposition.created
        for item in canonical_executions
    )
    replayed_count = sum(
        item.disposition is AccountSnapshotRefreshExecutionDisposition.replayed
        for item in canonical_executions
    )
    reused_count = sum(
        item.disposition is AccountSnapshotRefreshExecutionDisposition.reused
        for item in canonical_executions
    )
    if (
        _count(value.refresh_account_count) != refresh_count
        or _count(value.reuse_only_account_count) != reuse_count
        or _count(value.created_account_snapshot_count) != created_count
        or _count(value.replayed_account_snapshot_count) != replayed_count
        or _count(value.reused_account_snapshot_count) != reused_count
        or _count(value.selected_account_snapshot_count) != len(canonical_identities)
        or len(canonical_executions) != len(canonical_identities)
    ):
        raise _unavailable()
    return value


class MarketBackedSnapshotRefreshService:
    """Run market evidence refresh before the existing snapshot executor."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        market_service_factory: MarketServiceFactory = (create_production_market_evidence_service),
        executor_factory: SnapshotExecutorFactory = UserSnapshotRefreshExecutor,
        market_service: _MarketService | None = None,
        snapshot_executor: _SnapshotExecutor | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.market_service_factory = market_service_factory
        self.executor_factory = executor_factory
        self.market_service = market_service
        self.snapshot_executor = snapshot_executor

    def _require_idle_entry(self) -> None:
        if self.session.in_transaction():
            raise _unavailable()

    async def _dependency_must_leave_idle(self, dependency: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(
                f"Market-backed snapshot {dependency} dependency left an active transaction."
            )

    async def execute(
        self,
        command: ExecuteMarketBackedSnapshotRefreshCommand,
    ) -> ExecuteMarketBackedSnapshotRefreshResult:
        canonical = _validate_command(command)
        self._require_idle_entry()

        market_service = self.market_service
        if market_service is None:
            market_service = self.market_service_factory(self.session, self.settings)
        await self._dependency_must_leave_idle("market")
        try:
            market = await market_service.refresh(
                RefreshMarketEvidenceCommand(
                    user_id=canonical.user_id,
                    snapshot_timestamp=canonical.snapshot_timestamp,
                    created_at=canonical.created_at,
                )
            )
        except MarketEvidenceConflictError as exc:
            await self._dependency_must_leave_idle("market")
            raise _conflict() from exc
        except MarketEvidenceStateError as exc:
            await self._dependency_must_leave_idle("market")
            raise _unavailable() from exc
        except Exception:
            await self._dependency_must_leave_idle("market")
            raise
        await self._dependency_must_leave_idle("market")
        market = _validate_market_result(market, canonical)

        snapshot_executor = self.snapshot_executor
        if snapshot_executor is None:
            snapshot_executor = self.executor_factory(self.session)
        await self._dependency_must_leave_idle("snapshot")
        try:
            snapshots = await snapshot_executor.execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=canonical.user_id,
                    snapshot_timestamp=canonical.snapshot_timestamp,
                    granularity=canonical.granularity,
                    source=canonical.source,
                    calculation_version=canonical.calculation_version,
                    calculated_at=canonical.calculated_at,
                    created_at=canonical.created_at,
                    is_recalculated=canonical.is_recalculated,
                )
            )
        except SnapshotRefreshExecutionConflictError as exc:
            await self._dependency_must_leave_idle("snapshot")
            raise _conflict() from exc
        except SnapshotRefreshExecutionStateError as exc:
            await self._dependency_must_leave_idle("snapshot")
            raise _unavailable() from exc
        except Exception:
            await self._dependency_must_leave_idle("snapshot")
            raise
        await self._dependency_must_leave_idle("snapshot")
        snapshots = _validate_execution(
            snapshots,
            command=canonical,
            output_currency=market.output_currency,
        )
        return ExecuteMarketBackedSnapshotRefreshResult(
            market=market,
            snapshots=snapshots,
        )


__all__ = [
    "MarketBackedSnapshotRefreshService",
    "MarketServiceFactory",
    "SnapshotExecutorFactory",
]
