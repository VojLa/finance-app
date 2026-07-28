"""Authenticated application orchestration for manual net-worth snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.users import UserModel
from app.modules.net_worth.evidence_service import NetWorthEvidenceStateError
from app.modules.net_worth.manual_repository import ManualNetWorthSnapshotRepository
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceProjectionError,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)
from app.shared.errors import ApplicationError

CURRENT_NET_WORTH_CALCULATION_VERSION = 1
MANUAL_NET_WORTH_GRANULARITY = SnapshotGranularity.minute
MANUAL_NET_WORTH_SOURCE = SnapshotSource.manual_recalculation
Clock = Callable[[], datetime]


class NetWorthSnapshotUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="net_worth_snapshot_unavailable",
            message="Net-worth snapshot cannot be created from the current account data.",
            status_code=409,
        )


class NetWorthSnapshotConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="net_worth_snapshot_conflict",
            message="Net-worth snapshot conflicts with existing data.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class RecalculateNetWorthSnapshotCommand:
    principal: AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class RecalculateNetWorthSnapshotResult:
    snapshot_id: str
    status: Literal["created", "replayed"]
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    account_count: int
    selected_account_snapshot_count: int


class _ManualRepository(Protocol):
    async def load_user(self, user_id: str) -> UserModel | None: ...


class _SnapshotWriter(Protocol):
    async def write(
        self,
        command: WriteNetWorthSnapshotCommand,
    ) -> NetWorthSnapshotWriteResult: ...


type WriterFactory = Callable[[AsyncSession], _SnapshotWriter]


def current_net_worth_timestamp() -> datetime:
    return datetime.now(UTC)


def canonical_manual_net_worth_bucket(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise NetWorthSnapshotUnavailableError()
    normalized = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return normalized.replace(second=0, microsecond=0)


def _principal(command: object) -> AuthenticatedPrincipal:
    if not isinstance(command, RecalculateNetWorthSnapshotCommand):
        raise NetWorthSnapshotUnavailableError()
    principal = command.principal
    if (
        not isinstance(principal, AuthenticatedPrincipal)
        or not isinstance(principal.user_id, str)
        or not principal.user_id
        or principal.user_id != principal.user_id.strip()
    ):
        raise NetWorthSnapshotUnavailableError()
    return principal


def _persisted_currency(user: object, user_id: str) -> str:
    if not isinstance(user, UserModel) or user.id != user_id:
        raise NetWorthSnapshotUnavailableError()
    currency = user.base_currency
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise NetWorthSnapshotUnavailableError()
    return currency


class ManualNetWorthSnapshotService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _ManualRepository | None = None,
        clock: Clock = current_net_worth_timestamp,
        writer_factory: WriterFactory = NetWorthSnapshotWriter,
    ) -> None:
        self.session = session
        self.repository = repository or ManualNetWorthSnapshotRepository(session)
        self.clock = clock
        self.writer_factory = writer_factory

    async def recalculate(
        self,
        command: RecalculateNetWorthSnapshotCommand,
    ) -> RecalculateNetWorthSnapshotResult:
        try:
            principal = _principal(command)
            currency = _persisted_currency(
                await self.repository.load_user(principal.user_id),
                principal.user_id,
            )
        except NetWorthSnapshotUnavailableError:
            await self._close_read_transaction()
            raise
        except Exception:
            await self._close_read_transaction()
            raise

        try:
            await self.session.commit()
        except Exception:
            await self._close_read_transaction()
            raise
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError("Net-worth snapshot writer requires an idle database session.")

        bucket = canonical_manual_net_worth_bucket(self.clock())
        writer_command = WriteNetWorthSnapshotCommand(
            user_id=principal.user_id,
            snapshot_timestamp=bucket,
            granularity=MANUAL_NET_WORTH_GRANULARITY,
            currency=currency,
            source=MANUAL_NET_WORTH_SOURCE,
            calculation_version=CURRENT_NET_WORTH_CALCULATION_VERSION,
            calculated_at=bucket,
            created_at=bucket,
            is_recalculated=True,
        )
        try:
            result = await self.writer_factory(self.session).write(writer_command)
        except NetWorthSnapshotWriteConflictError as exc:
            raise NetWorthSnapshotConflictError() from exc
        except (
            NetWorthEvidenceStateError,
            NetWorthSnapshotPersistenceProjectionError,
            NetWorthSnapshotWriteStateError,
        ) as exc:
            raise NetWorthSnapshotUnavailableError() from exc

        return RecalculateNetWorthSnapshotResult(
            snapshot_id=result.snapshot_id,
            status=result.disposition.value,
            timestamp=result.timestamp,
            granularity=result.granularity,
            currency=result.currency,
            account_count=result.account_count,
            selected_account_snapshot_count=result.selected_account_snapshot_count,
        )

    async def _close_read_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
