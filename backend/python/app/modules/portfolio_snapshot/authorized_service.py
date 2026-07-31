"""Transaction owner for the existing authorized exact portfolio snapshot API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.portfolio_snapshot.authorized_reader import (
    AccessChecker,
    AuthorizedExactPortfolioSnapshotReader,
    PortfolioSnapshotUnavailableError,
    ReadAuthorizedPortfolioSnapshotCommand,
    ReadAuthorizedPortfolioSnapshotResult,
    ReaderFactory,
    portfolio_snapshot_unavailable,
    validate_authorized_command,
)


class _AuthorizedReader(Protocol):
    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedPortfolioSnapshotResult: ...


type AuthorizedReaderFactory = Callable[[AsyncSession], _AuthorizedReader]


class AuthorizedPortfolioSnapshotService:
    """Own one coherent transaction around the shared authorized exact reader."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        reader_factory: ReaderFactory | None = None,
        access_checker: AccessChecker | None = None,
        authorized_reader_factory: AuthorizedReaderFactory | None = None,
    ) -> None:
        self.session = session
        self.reader_factory = reader_factory
        self.access_checker = access_checker
        self.authorized_reader_factory = authorized_reader_factory

    def _authorized_reader(self) -> _AuthorizedReader:
        if self.authorized_reader_factory is not None:
            return self.authorized_reader_factory(self.session)
        kwargs: dict[str, object] = {}
        if self.reader_factory is not None:
            kwargs["reader_factory"] = self.reader_factory
        if self.access_checker is not None:
            kwargs["access_checker"] = self.access_checker
        return AuthorizedExactPortfolioSnapshotReader(self.session, **kwargs)  # type: ignore[arg-type]

    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedPortfolioSnapshotResult:
        try:
            canonical = validate_authorized_command(command)
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
                result = await self._authorized_reader().read(canonical)
                if type(result) is not ReadAuthorizedPortfolioSnapshotResult:
                    raise portfolio_snapshot_unavailable()
        except (AccountNotFoundError, AccountAccessDeniedError):
            raise
        except PortfolioSnapshotUnavailableError:
            raise
        except (SQLAlchemyError, AttributeError, TypeError, ValueError) as exc:
            raise portfolio_snapshot_unavailable() from exc
        finally:
            await self._require_idle(
                "Authorized portfolio snapshot read left an active database transaction."
            )

        return result

    async def _require_idle(self, message: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(message)

    async def _close_active_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()


__all__ = [
    "AuthorizedPortfolioSnapshotService",
    "PortfolioSnapshotUnavailableError",
    "ReadAuthorizedPortfolioSnapshotCommand",
    "ReadAuthorizedPortfolioSnapshotResult",
]
