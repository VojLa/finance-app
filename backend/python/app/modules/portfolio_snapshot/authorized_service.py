"""Authorized transaction boundary for one exact portfolio snapshot read."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.common import TIMESTAMP
from app.db.models.enums import AccountMemberRole
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    AuthorizedAccount,
    require_account_access,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioSnapshotView,
    SnapshotGranularity,
)
from app.modules.portfolio_snapshot.projection import PortfolioSnapshotProjectionError
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    PortfolioSnapshotReader,
    PortfolioSnapshotReadError,
    ReadExactPortfolioSnapshotCommand,
)
from app.shared.errors import ApplicationError

_POSTGRES_INTEGER_MAX = 2_147_483_647
_READ_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
    AccountMemberRole.viewer,
}


class PortfolioSnapshotUnavailableError(ApplicationError):
    """Public failure for unavailable or inconsistent persisted snapshot evidence."""

    def __init__(self) -> None:
        super().__init__(
            code="portfolio_snapshot_unavailable",
            message="The requested portfolio snapshot is unavailable.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class ReadAuthorizedPortfolioSnapshotCommand:
    """Exact snapshot identity requested by one authenticated principal."""

    principal: AuthenticatedPrincipal
    account_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    required_snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadAuthorizedPortfolioSnapshotResult:
    """Public-safe result containing only the pure portfolio view."""

    view: PortfolioSnapshotView


class _Reader(Protocol):
    async def read(
        self,
        command: ReadExactPortfolioSnapshotCommand,
    ) -> CompletePortfolioSnapshotRead: ...


type ReaderFactory = Callable[[AsyncSession], _Reader]
type AccessChecker = Callable[..., Awaitable[AuthorizedAccount]]


def _fail() -> PortfolioSnapshotUnavailableError:
    return PortfolioSnapshotUnavailableError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or any(character < "A" or character > "Z" for character in result):
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


def _version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _command(value: object) -> ReadAuthorizedPortfolioSnapshotCommand:
    if not isinstance(value, ReadAuthorizedPortfolioSnapshotCommand):
        raise _fail()
    principal = value.principal
    if not isinstance(principal, AuthenticatedPrincipal):
        raise _fail()
    _nonblank(principal.user_id)
    account_id = _nonblank(value.account_id)
    if not isinstance(value.granularity, SnapshotGranularity):
        raise _fail()
    timestamp = _aligned_timestamp(value.timestamp, value.granularity)
    currency = _currency(value.currency)
    version = _version(value.calculation_version)
    required_snapshot_id = (
        None if value.required_snapshot_id is None else _nonblank(value.required_snapshot_id)
    )
    return ReadAuthorizedPortfolioSnapshotCommand(
        principal=principal,
        account_id=account_id,
        timestamp=timestamp,
        granularity=value.granularity,
        currency=currency,
        calculation_version=version,
        required_snapshot_id=required_snapshot_id,
    )


def _validate_read(
    value: object,
    *,
    authorized: AuthorizedAccount,
    required_snapshot_id: str | None,
) -> PortfolioSnapshotView:
    if not isinstance(value, CompletePortfolioSnapshotRead):
        raise _fail()
    selected_snapshot_id = _nonblank(value.selected_snapshot_id)
    view = value.view
    item_ids = value.selected_item_ids
    if isinstance(item_ids, tuple):
        for item_id in item_ids:
            _nonblank(item_id)
    if (
        not isinstance(view, PortfolioSnapshotView)
        or view.snapshot_id != selected_snapshot_id
        or view.account.account_id != authorized.account_id
        or (required_snapshot_id is not None and selected_snapshot_id != required_snapshot_id)
        or not isinstance(item_ids, tuple)
        or item_ids != tuple(sorted(item_ids))
        or len(item_ids) != len(set(item_ids))
        or len(item_ids) != len(view.positions)
    ):
        raise _fail()
    return view


class AuthorizedPortfolioSnapshotService:
    """Authorize and read one immutable snapshot in one coherent transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        reader_factory: ReaderFactory = PortfolioSnapshotReader,
        access_checker: AccessChecker = require_account_access,
    ) -> None:
        self.session = session
        self.reader_factory = reader_factory
        self.access_checker = access_checker

    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedPortfolioSnapshotResult:
        try:
            canonical = _command(command)
        except PortfolioSnapshotUnavailableError:
            await self._close_active_transaction()
            raise

        try:
            await self.session.commit()
        except Exception:
            await self._close_active_transaction()
            raise
        await self._require_idle(
            "Authorized portfolio snapshot read requires an idle database session."
        )

        try:
            async with self.session.begin():
                await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                authorized = await self.access_checker(
                    session=self.session,
                    principal=canonical.principal,
                    account_id=canonical.account_id,
                    allowed_roles=_READ_ROLES,
                    include_archived=False,
                    for_update=False,
                )
                if (
                    not isinstance(authorized, AuthorizedAccount)
                    or authorized.account_id != canonical.account_id
                ):
                    raise _fail()
                reader_command = ReadExactPortfolioSnapshotCommand(
                    account_id=canonical.account_id,
                    timestamp=canonical.timestamp,
                    granularity=canonical.granularity,
                    currency=canonical.currency,
                    calculation_version=canonical.calculation_version,
                    required_snapshot_id=canonical.required_snapshot_id,
                )
                read = await self.reader_factory(self.session).read(reader_command)
                view = _validate_read(
                    read,
                    authorized=authorized,
                    required_snapshot_id=canonical.required_snapshot_id,
                )
        except (AccountNotFoundError, AccountAccessDeniedError):
            raise
        except PortfolioSnapshotUnavailableError:
            raise
        except (
            PortfolioSnapshotReadError,
            PortfolioSnapshotProjectionError,
            SQLAlchemyError,
            TypeError,
            ValueError,
        ) as exc:
            raise _fail() from exc
        finally:
            await self._require_idle(
                "Authorized portfolio snapshot read left an active database transaction."
            )

        return ReadAuthorizedPortfolioSnapshotResult(view=view)

    async def _require_idle(self, message: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(message)

    async def _close_active_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
