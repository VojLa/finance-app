"""Authorized coherent read service for snapshot-backed portfolio history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.modules.portfolio_history.models import (
    PersistedPortfolioHistoryPoint,
    PortfolioHistoryRange,
    PortfolioHistoryView,
)
from app.modules.portfolio_history.repository import (
    PersistedPortfolioHistoryUser,
    PortfolioHistoryRepository,
)
from app.modules.portfolio_history.selection import (
    PortfolioHistorySelectionError,
    canonicalize_portfolio_history_points,
    downsample_portfolio_history_points,
    portfolio_history_range_start,
    public_portfolio_history_points,
    validate_currency,
    validate_nonblank,
    validate_timestamp,
)
from app.shared.errors import ApplicationError

Clock = Callable[[], datetime]


class PortfolioHistoryUnavailableError(ApplicationError):
    """Public-safe failure for unavailable or inconsistent history evidence."""

    def __init__(self) -> None:
        super().__init__(
            code="portfolio_history_unavailable",
            message="Portfolio history is unavailable.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class ReadPortfolioHistoryCommand:
    principal: AuthenticatedPrincipal
    range: PortfolioHistoryRange


@dataclass(frozen=True, slots=True)
class ReadPortfolioHistoryResult:
    history: PortfolioHistoryView
    selected_snapshot_ids: tuple[str, ...]


class _Repository(Protocol):
    async def load_user(self, user_id: str) -> PersistedPortfolioHistoryUser | None: ...

    async def load_candidate_points(
        self,
        *,
        user_id: str,
        currency: str,
        start: datetime | None,
        end: datetime,
    ) -> tuple[PersistedPortfolioHistoryPoint, ...]: ...


type RepositoryFactory = Callable[[AsyncSession], _Repository]


def current_portfolio_history_timestamp() -> datetime:
    """Produce a naive UTC TIMESTAMP(3) clock value at the dependency boundary."""

    value = datetime.now(UTC)
    return value.replace(tzinfo=None, microsecond=value.microsecond // 1000 * 1000)


def _unavailable() -> PortfolioHistoryUnavailableError:
    return PortfolioHistoryUnavailableError()


def _canonical_command(value: object) -> ReadPortfolioHistoryCommand:
    if (
        type(value) is not ReadPortfolioHistoryCommand
        or type(value.principal) is not AuthenticatedPrincipal
        or type(value.range) is not PortfolioHistoryRange
    ):
        raise _unavailable()
    try:
        user_id = validate_nonblank(value.principal.user_id)
    except PortfolioHistorySelectionError as exc:
        raise _unavailable() from exc
    if user_id != value.principal.user_id:
        raise _unavailable()
    return value


class SnapshotBackedPortfolioHistoryService:
    """Own one read-only transaction and pure deterministic history selection."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = current_portfolio_history_timestamp,
        repository_factory: RepositoryFactory = PortfolioHistoryRepository,
    ) -> None:
        self.session = session
        self.clock = clock
        self.repository_factory = repository_factory

    async def read(self, command: object) -> ReadPortfolioHistoryResult:
        try:
            canonical = _canonical_command(command)
            end = validate_timestamp(self.clock())
            start = portfolio_history_range_start(canonical.range, end)
        except (PortfolioHistorySelectionError, PortfolioHistoryUnavailableError) as exc:
            await self._close_active_transaction()
            raise _unavailable() from exc

        try:
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self._close_active_transaction()
            raise _unavailable() from exc
        except Exception:
            await self._close_active_transaction()
            raise
        await self._require_idle()

        user: PersistedPortfolioHistoryUser | None = None
        candidates: tuple[PersistedPortfolioHistoryPoint, ...] = ()
        try:
            async with self.session.begin():
                await self.session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                repository = self.repository_factory(self.session)
                user = await repository.load_user(canonical.principal.user_id)
                if type(user) is not PersistedPortfolioHistoryUser:
                    raise _unavailable()
                user_id = validate_nonblank(user.user_id)
                currency = validate_currency(user.base_currency)
                if user_id != canonical.principal.user_id:
                    raise _unavailable()
                candidates = await repository.load_candidate_points(
                    user_id=user_id,
                    currency=currency,
                    start=start,
                    end=end,
                )
                if type(candidates) is not tuple:
                    raise _unavailable()
        except PortfolioHistoryUnavailableError:
            raise
        except (PortfolioHistorySelectionError, SQLAlchemyError, AttributeError, TypeError) as exc:
            raise _unavailable() from exc
        finally:
            await self._require_idle()

        try:
            if type(user) is not PersistedPortfolioHistoryUser:
                raise _unavailable()
            user_id = validate_nonblank(user.user_id)
            currency = validate_currency(user.base_currency)
            canonical_points = canonicalize_portfolio_history_points(
                candidates,
                user_id=user_id,
                currency=currency,
                start=start,
                end=end,
            )
            selected = downsample_portfolio_history_points(canonical_points)
            history = PortfolioHistoryView(
                range=canonical.range,
                currency=currency,
                points=public_portfolio_history_points(selected),
            )
            return ReadPortfolioHistoryResult(
                history=history,
                selected_snapshot_ids=tuple(point.snapshot_id for point in selected),
            )
        except (PortfolioHistorySelectionError, AttributeError, TypeError, ValueError) as exc:
            raise _unavailable() from exc
        finally:
            await self._require_idle()

    async def _require_idle(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise _unavailable()

    async def _close_active_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()


__all__ = [
    "Clock",
    "PortfolioHistoryUnavailableError",
    "ReadPortfolioHistoryCommand",
    "ReadPortfolioHistoryResult",
    "SnapshotBackedPortfolioHistoryService",
    "current_portfolio_history_timestamp",
]
