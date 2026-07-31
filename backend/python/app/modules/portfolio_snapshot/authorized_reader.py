"""Shared authorization boundary for one exact portfolio snapshot read."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

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
_READ_ROLES = frozenset(
    (
        AccountMemberRole.owner,
        AccountMemberRole.admin,
        AccountMemberRole.editor,
        AccountMemberRole.viewer,
    )
)


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


def portfolio_snapshot_unavailable() -> PortfolioSnapshotUnavailableError:
    """Return the single public-safe unavailable error."""

    return PortfolioSnapshotUnavailableError()


def _nonblank(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise portfolio_snapshot_unavailable()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or any(character < "A" or character > "Z" for character in result):
        raise portfolio_snapshot_unavailable()
    return result


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        type(value) is not datetime
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise portfolio_snapshot_unavailable()
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
        raise portfolio_snapshot_unavailable()
    if not aligned:
        raise portfolio_snapshot_unavailable()
    return timestamp


def _version(value: object) -> int:
    if type(value) is not int or not 1 <= value <= _POSTGRES_INTEGER_MAX:
        raise portfolio_snapshot_unavailable()
    return value


def validate_authorized_command(value: object) -> ReadAuthorizedPortfolioSnapshotCommand:
    """Validate and canonically copy one exact authorized read command."""

    if type(value) is not ReadAuthorizedPortfolioSnapshotCommand:
        raise portfolio_snapshot_unavailable()
    principal = value.principal
    if type(principal) is not AuthenticatedPrincipal:
        raise portfolio_snapshot_unavailable()
    _nonblank(principal.user_id)
    account_id = _nonblank(value.account_id)
    if type(value.granularity) is not SnapshotGranularity:
        raise portfolio_snapshot_unavailable()
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
    if type(value) is not CompletePortfolioSnapshotRead:
        raise portfolio_snapshot_unavailable()
    selected_snapshot_id = _nonblank(value.selected_snapshot_id)
    view = value.view
    item_ids = value.selected_item_ids
    if type(item_ids) is tuple:
        for item_id in item_ids:
            _nonblank(item_id)
    if (
        type(view) is not PortfolioSnapshotView
        or view.snapshot_id != selected_snapshot_id
        or view.account.account_id != authorized.account_id
        or (required_snapshot_id is not None and selected_snapshot_id != required_snapshot_id)
        or type(item_ids) is not tuple
        or item_ids != tuple(sorted(item_ids))
        or len(item_ids) != len(set(item_ids))
        or len(item_ids) != len(view.positions)
    ):
        raise portfolio_snapshot_unavailable()
    return view


class AuthorizedExactPortfolioSnapshotReader:
    """Authorize and read one exact snapshot inside a caller-owned transaction."""

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
            canonical = validate_authorized_command(command)
            if self.session.in_transaction() is not True:
                raise portfolio_snapshot_unavailable()
            authorized = await self.access_checker(
                session=self.session,
                principal=canonical.principal,
                account_id=canonical.account_id,
                allowed_roles=_READ_ROLES,
                include_archived=False,
                for_update=False,
            )
            if (
                type(authorized) is not AuthorizedAccount
                or authorized.account_id != canonical.account_id
                or authorized.role not in _READ_ROLES
            ):
                raise portfolio_snapshot_unavailable()
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
            if self.session.in_transaction() is not True:
                raise portfolio_snapshot_unavailable()
            return ReadAuthorizedPortfolioSnapshotResult(view=view)
        except (AccountNotFoundError, AccountAccessDeniedError):
            raise
        except PortfolioSnapshotUnavailableError:
            raise
        except (
            PortfolioSnapshotReadError,
            PortfolioSnapshotProjectionError,
            SQLAlchemyError,
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            raise portfolio_snapshot_unavailable() from exc
