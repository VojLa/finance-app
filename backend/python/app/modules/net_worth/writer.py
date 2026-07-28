"""Atomic internal writer for exact physical net-worth snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.common import TIMESTAMP
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    CompleteNetWorthEvidence,
    NetWorthEvidenceService,
    NetWorthEvidenceStateError,
)
from app.modules.net_worth.persistence_projection import (
    ExpectedNetWorthSnapshotPersistence,
    ExpectedNetWorthSnapshotRow,
    NetWorthSnapshotPersistenceAudit,
    NetWorthSnapshotPersistenceMetadata,
    NetWorthSnapshotPersistenceProjectionError,
    build_net_worth_snapshot_persistence_projection,
)
from app.modules.net_worth.writer_repository import NetWorthSnapshotWriterRepository

_STATE_MESSAGE = "Net-worth snapshot could not be persisted."
_CONFLICT_MESSAGE = "Net-worth snapshot conflicts with persisted state."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}


class NetWorthSnapshotWriteStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class NetWorthSnapshotWriteConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


class NetWorthSnapshotWriteDisposition(StrEnum):
    created = "created"
    replayed = "replayed"


@dataclass(frozen=True, slots=True)
class WriteNetWorthSnapshotCommand:
    user_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool


@dataclass(frozen=True, slots=True)
class NetWorthSnapshotWriteResult:
    snapshot_id: str
    user_id: str
    disposition: NetWorthSnapshotWriteDisposition
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    account_count: int
    selected_account_snapshot_count: int


class _EvidenceBuilder(Protocol):
    async def build(
        self,
        command: BuildNetWorthEvidenceCommand,
    ) -> CompleteNetWorthEvidence: ...


class _Repository(Protocol):
    async def set_transaction_serializable(self) -> None: ...

    async def acquire_snapshot_lock(
        self,
        *,
        user_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> None: ...

    async def load_existing_snapshot(
        self,
        *,
        user_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> NetWorthSnapshotModel | None: ...

    async def load_snapshot_by_id(
        self,
        snapshot_id: str,
    ) -> NetWorthSnapshotModel | None: ...

    def add_snapshot(self, snapshot: NetWorthSnapshotModel) -> None: ...

    async def flush(self) -> None: ...

    async def reload_snapshot(
        self,
        snapshot_id: str,
    ) -> NetWorthSnapshotModel | None: ...


type _ProjectionBuilder = Callable[
    [CompleteNetWorthEvidence, NetWorthSnapshotPersistenceMetadata],
    ExpectedNetWorthSnapshotPersistence,
]


def _fail() -> NetWorthSnapshotWriteStateError:
    return NetWorthSnapshotWriteStateError()


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


def _validate_command(command: object) -> WriteNetWorthSnapshotCommand:
    if not isinstance(command, WriteNetWorthSnapshotCommand):
        raise _fail()
    user_id = _nonblank(command.user_id)
    if (
        not isinstance(command.granularity, SnapshotGranularity)
        or not isinstance(command.source, SnapshotSource)
        or not isinstance(command.calculation_version, int)
        or isinstance(command.calculation_version, bool)
        or not 1 <= command.calculation_version <= _POSTGRES_INTEGER_MAX
        or not isinstance(command.is_recalculated, bool)
        or command.is_recalculated is not (command.source is SnapshotSource.manual_recalculation)
    ):
        raise _fail()
    return WriteNetWorthSnapshotCommand(
        user_id=user_id,
        snapshot_timestamp=_aligned_timestamp(
            command.snapshot_timestamp,
            command.granularity,
        ),
        granularity=command.granularity,
        currency=_currency(command.currency),
        source=command.source,
        calculation_version=command.calculation_version,
        calculated_at=_timestamp(command.calculated_at),
        created_at=_timestamp(command.created_at),
        is_recalculated=command.is_recalculated,
    )


_PHYSICAL_ATTRIBUTES = (
    "id",
    "user_id",
    "timestamp",
    "granularity",
    "source",
    "currency",
    "cash_value",
    "portfolio_value",
    "liabilities_value",
    "total_net_worth",
    "is_recalculated",
    "calculated_at",
    "calculation_version",
    "created_at",
    "cash_value_by_currency",
    "portfolio_value_by_currency",
    "liabilities_value_by_currency",
    "total_net_worth_by_currency",
    "exchange_rates",
)


def _matches(
    persisted: object,
    expected: ExpectedNetWorthSnapshotRow,
) -> bool:
    if not isinstance(persisted, NetWorthSnapshotModel):
        return False
    values = expected.model_values()
    return all(getattr(persisted, name) == values[name] for name in _PHYSICAL_ATTRIBUTES)


def _validate_projection(
    projection: object,
    command: WriteNetWorthSnapshotCommand,
) -> ExpectedNetWorthSnapshotPersistence:
    if not isinstance(projection, ExpectedNetWorthSnapshotPersistence):
        raise _fail()
    row = projection.snapshot
    audit = projection.audit
    if (
        not isinstance(row, ExpectedNetWorthSnapshotRow)
        or not isinstance(audit, NetWorthSnapshotPersistenceAudit)
        or row.user_id != command.user_id
        or row.timestamp != command.snapshot_timestamp
        or row.granularity is not command.granularity
        or row.currency != command.currency
        or row.source is not command.source
        or row.calculation_version != command.calculation_version
        or row.calculated_at != command.calculated_at
        or row.created_at != command.created_at
        or row.is_recalculated is not command.is_recalculated
        or not isinstance(audit.selected_account_ids, tuple)
        or not isinstance(audit.selected_account_snapshot_ids, tuple)
        or not isinstance(audit.selected_identities, tuple)
        or len(audit.selected_account_ids) != len(audit.selected_account_snapshot_ids)
        or len(audit.selected_account_ids) != len(audit.selected_identities)
    ):
        raise _fail()
    return projection


def _result(
    projection: ExpectedNetWorthSnapshotPersistence,
    disposition: NetWorthSnapshotWriteDisposition,
) -> NetWorthSnapshotWriteResult:
    snapshot = projection.snapshot
    return NetWorthSnapshotWriteResult(
        snapshot_id=snapshot.id,
        user_id=snapshot.user_id,
        disposition=disposition,
        timestamp=snapshot.timestamp,
        granularity=snapshot.granularity,
        currency=snapshot.currency,
        account_count=len(projection.audit.selected_account_ids),
        selected_account_snapshot_count=len(projection.audit.selected_account_snapshot_ids),
    )


def _sqlstate(error: BaseException) -> str | None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str):
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


class NetWorthSnapshotWriter:
    """Own bounded SERIALIZABLE transaction attempts for one exact snapshot."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _Repository | None = None,
        evidence_service: _EvidenceBuilder | None = None,
        projection_builder: _ProjectionBuilder = (build_net_worth_snapshot_persistence_projection),
    ) -> None:
        self.session = session
        self.repository = repository or NetWorthSnapshotWriterRepository(session)
        self.evidence_service = evidence_service or NetWorthEvidenceService(session)
        self.projection_builder = projection_builder

    async def write(
        self,
        command: WriteNetWorthSnapshotCommand,
    ) -> NetWorthSnapshotWriteResult:
        canonical = _validate_command(command)
        if self.session.in_transaction():
            raise _fail()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    return await self._write_attempt(canonical)
            except (
                NetWorthEvidenceStateError,
                NetWorthSnapshotPersistenceProjectionError,
                NetWorthSnapshotWriteConflictError,
                NetWorthSnapshotWriteStateError,
            ):
                raise
            except SQLAlchemyError as exc:
                if (
                    _sqlstate(exc) in _RETRYABLE_SQLSTATES
                    and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise _fail() from exc
        raise _fail()

    async def _write_attempt(
        self,
        command: WriteNetWorthSnapshotCommand,
    ) -> NetWorthSnapshotWriteResult:
        await self.repository.set_transaction_serializable()
        await self.repository.acquire_snapshot_lock(
            user_id=command.user_id,
            timestamp=command.snapshot_timestamp,
            currency=command.currency,
            granularity=command.granularity,
        )
        evidence = await self.evidence_service.build(
            BuildNetWorthEvidenceCommand(
                user_id=command.user_id,
                timestamp=command.snapshot_timestamp,
                granularity=command.granularity,
                currency=command.currency,
                calculation_version=command.calculation_version,
            )
        )
        projection = _validate_projection(
            self.projection_builder(
                evidence,
                NetWorthSnapshotPersistenceMetadata(
                    source=command.source,
                    calculated_at=command.calculated_at,
                    created_at=command.created_at,
                    is_recalculated=command.is_recalculated,
                ),
            ),
            command,
        )
        expected = projection.snapshot
        existing = await self.repository.load_existing_snapshot(
            user_id=command.user_id,
            timestamp=command.snapshot_timestamp,
            currency=command.currency,
            granularity=command.granularity,
        )
        if existing is not None:
            if not _matches(existing, expected):
                raise NetWorthSnapshotWriteConflictError()
            return _result(projection, NetWorthSnapshotWriteDisposition.replayed)

        id_conflict = await self.repository.load_snapshot_by_id(expected.id)
        if id_conflict is not None:
            raise NetWorthSnapshotWriteConflictError()
        self.repository.add_snapshot(NetWorthSnapshotModel(**expected.model_values()))
        await self.repository.flush()
        persisted = await self.repository.reload_snapshot(expected.id)
        if not _matches(persisted, expected):
            raise _fail()
        return _result(projection, NetWorthSnapshotWriteDisposition.created)
