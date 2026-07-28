"""Authorized application orchestration for manual account snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import (
    AccountMemberRole,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    require_account_access,
)
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceProjectionError,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriteConflictError,
    AccountSnapshotWriter,
    AccountSnapshotWriteResult,
    AccountSnapshotWriteStateError,
    WriteAccountSnapshotCommand,
)
from app.shared.errors import ApplicationError

CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION = 1
MANUAL_SNAPSHOT_GRANULARITY = SnapshotGranularity.minute
MANUAL_SNAPSHOT_SOURCE = SnapshotSource.manual_recalculation
WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}
Clock = Callable[[], datetime]


class AccountSnapshotUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_snapshot_unavailable",
            message="Account snapshot cannot be created from the current account data.",
            status_code=409,
        )


class AccountSnapshotConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_snapshot_conflict",
            message="Account snapshot conflicts with existing data.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class RecalculateAccountSnapshotCommand:
    principal: AuthenticatedPrincipal
    account_id: str


@dataclass(frozen=True, slots=True)
class RecalculateAccountSnapshotResult:
    snapshot_id: str
    account_id: str
    status: Literal["created", "replayed"]
    item_count: int
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str


class _SnapshotWriter(Protocol):
    async def write(
        self,
        command: WriteAccountSnapshotCommand,
    ) -> AccountSnapshotWriteResult: ...


type WriterFactory = Callable[[AsyncSession], _SnapshotWriter]


def current_snapshot_timestamp() -> datetime:
    return datetime.now(UTC)


def canonical_manual_snapshot_bucket(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise AccountSnapshotUnavailableError()
    normalized = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return normalized.replace(second=0, microsecond=0)


class ManualAccountSnapshotService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = current_snapshot_timestamp,
        writer_factory: WriterFactory = AccountSnapshotWriter,
    ) -> None:
        self.session = session
        self.clock = clock
        self.writer_factory = writer_factory

    async def recalculate(
        self,
        command: RecalculateAccountSnapshotCommand,
    ) -> RecalculateAccountSnapshotResult:
        if (
            not isinstance(command, RecalculateAccountSnapshotCommand)
            or not isinstance(command.account_id, str)
            or not command.account_id
            or command.account_id != command.account_id.strip()
        ):
            await self._close_authorization_transaction()
            raise AccountNotFoundError()

        try:
            await require_account_access(
                session=self.session,
                principal=command.principal,
                account_id=command.account_id,
                allowed_roles=WRITE_ROLES,
            )
        except (AccountNotFoundError, AccountAccessDeniedError) as exc:
            await self._close_authorization_transaction()
            raise AccountNotFoundError() from exc
        except Exception:
            await self._close_authorization_transaction()
            raise

        # Authentication and membership resolution autobegin on the request
        # session. Finish that read transaction before entering the 5I-D writer,
        # which deliberately requires and owns a fresh outer transaction.
        await self.session.commit()
        if self.session.in_transaction():
            raise RuntimeError("Snapshot writer requires an idle database session.")

        bucket = canonical_manual_snapshot_bucket(self.clock())
        writer_command = WriteAccountSnapshotCommand(
            account_id=command.account_id,
            snapshot_timestamp=bucket,
            granularity=MANUAL_SNAPSHOT_GRANULARITY,
            source=MANUAL_SNAPSHOT_SOURCE,
            calculation_version=CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION,
            calculated_at=bucket,
            created_at=bucket,
            is_recalculated=True,
        )
        try:
            result = await self.writer_factory(self.session).write(writer_command)
        except AccountSnapshotWriteConflictError as exc:
            raise AccountSnapshotConflictError() from exc
        except (
            AccountSnapshotEvidenceStateError,
            AccountSnapshotPersistenceProjectionError,
            AccountSnapshotWriteStateError,
        ) as exc:
            raise AccountSnapshotUnavailableError() from exc

        return RecalculateAccountSnapshotResult(
            snapshot_id=result.snapshot_id,
            account_id=result.account_id,
            status=result.disposition.value,
            item_count=result.item_count,
            timestamp=result.timestamp,
            granularity=result.granularity,
            currency=result.currency,
        )

    async def _close_authorization_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
