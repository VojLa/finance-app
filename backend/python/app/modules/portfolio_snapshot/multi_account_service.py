"""Authorized coherent read service for an exact account snapshot set."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.portfolio_snapshot.aggregate_models import MultiAccountPortfolioView
from app.modules.portfolio_snapshot.aggregation import (
    MultiAccountPortfolioProjectionError,
    build_multi_account_portfolio_view,
)
from app.modules.portfolio_snapshot.authorized_reader import (
    AuthorizedExactPortfolioSnapshotReader,
    PortfolioSnapshotUnavailableError,
    ReadAuthorizedPortfolioSnapshotCommand,
    ReadAuthorizedPortfolioSnapshotResult,
    portfolio_snapshot_unavailable,
    validate_authorized_command,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioSnapshotView,
    SnapshotGranularity,
)


@dataclass(frozen=True, slots=True)
class ExactAccountSnapshotSelection:
    """One explicit account selector and optional immutable lineage guard."""

    account_id: str
    required_snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadAuthorizedMultiAccountPortfolioSnapshotCommand:
    """Complete explicit identity for one coherent account snapshot set."""

    principal: AuthenticatedPrincipal
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    accounts: tuple[ExactAccountSnapshotSelection, ...]


@dataclass(frozen=True, slots=True)
class ReadAuthorizedMultiAccountPortfolioSnapshotResult:
    """Public-safe exact multi-account portfolio result."""

    portfolio: MultiAccountPortfolioView


class _AuthorizedReader(Protocol):
    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedPortfolioSnapshotResult: ...


type AuthorizedReaderFactory = Callable[[AsyncSession], _AuthorizedReader]
type AggregateBuilder = Callable[
    [tuple[PortfolioSnapshotView, ...]],
    MultiAccountPortfolioView,
]


def _canonical_command(
    value: object,
) -> ReadAuthorizedMultiAccountPortfolioSnapshotCommand:
    if (
        type(value) is not ReadAuthorizedMultiAccountPortfolioSnapshotCommand
        or type(value.accounts) is not tuple
        or not value.accounts
    ):
        raise portfolio_snapshot_unavailable()
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    canonical: list[ExactAccountSnapshotSelection] = []
    for selector in value.accounts:
        if type(selector) is not ExactAccountSnapshotSelection:
            raise portfolio_snapshot_unavailable()
        validated = validate_authorized_command(
            ReadAuthorizedPortfolioSnapshotCommand(
                principal=value.principal,
                account_id=selector.account_id,
                timestamp=value.timestamp,
                granularity=value.granularity,
                currency=value.currency,
                calculation_version=value.calculation_version,
                required_snapshot_id=selector.required_snapshot_id,
            )
        )
        if validated.account_id in account_ids or (
            validated.required_snapshot_id is not None
            and validated.required_snapshot_id in snapshot_ids
        ):
            raise portfolio_snapshot_unavailable()
        account_ids.add(validated.account_id)
        if validated.required_snapshot_id is not None:
            snapshot_ids.add(validated.required_snapshot_id)
        canonical.append(
            ExactAccountSnapshotSelection(
                account_id=validated.account_id,
                required_snapshot_id=validated.required_snapshot_id,
            )
        )
    ordered = tuple(
        sorted(
            canonical,
            key=lambda selector: (
                selector.account_id,
                selector.required_snapshot_id or "",
            ),
        )
    )
    reference = validate_authorized_command(
        ReadAuthorizedPortfolioSnapshotCommand(
            principal=value.principal,
            account_id=ordered[0].account_id,
            timestamp=value.timestamp,
            granularity=value.granularity,
            currency=value.currency,
            calculation_version=value.calculation_version,
            required_snapshot_id=ordered[0].required_snapshot_id,
        )
    )
    return ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
        principal=reference.principal,
        timestamp=reference.timestamp,
        granularity=reference.granularity,
        currency=reference.currency,
        calculation_version=reference.calculation_version,
        accounts=ordered,
    )


class AuthorizedMultiAccountPortfolioSnapshotService:
    """Read an explicit account set inside one repeatable-read transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        authorized_reader_factory: AuthorizedReaderFactory = (
            AuthorizedExactPortfolioSnapshotReader
        ),
        aggregate_builder: AggregateBuilder = build_multi_account_portfolio_view,
    ) -> None:
        self.session = session
        self.authorized_reader_factory = authorized_reader_factory
        self.aggregate_builder = aggregate_builder

    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedMultiAccountPortfolioSnapshotResult:
        try:
            canonical = _canonical_command(command)
        except PortfolioSnapshotUnavailableError:
            await self._close_active_transaction()
            raise

        try:
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self._close_active_transaction()
            raise portfolio_snapshot_unavailable() from exc
        except Exception:
            await self._close_active_transaction()
            raise
        await self._require_idle(
            "Authorized multi-account snapshot read requires an idle database session."
        )

        try:
            async with self.session.begin():
                await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                authorized_reader = self.authorized_reader_factory(self.session)
                views: list[PortfolioSnapshotView] = []
                for selector in canonical.accounts:
                    result = await authorized_reader.read(
                        ReadAuthorizedPortfolioSnapshotCommand(
                            principal=canonical.principal,
                            account_id=selector.account_id,
                            timestamp=canonical.timestamp,
                            granularity=canonical.granularity,
                            currency=canonical.currency,
                            calculation_version=canonical.calculation_version,
                            required_snapshot_id=selector.required_snapshot_id,
                        )
                    )
                    if type(result) is not ReadAuthorizedPortfolioSnapshotResult:
                        raise portfolio_snapshot_unavailable()
                    views.append(result.view)
                portfolio = self.aggregate_builder(tuple(views))
                if type(portfolio) is not MultiAccountPortfolioView:
                    raise portfolio_snapshot_unavailable()
        except (AccountNotFoundError, AccountAccessDeniedError):
            raise
        except PortfolioSnapshotUnavailableError:
            raise
        except (
            MultiAccountPortfolioProjectionError,
            SQLAlchemyError,
            AttributeError,
            TypeError,
            ValueError,
        ) as exc:
            raise portfolio_snapshot_unavailable() from exc
        finally:
            await self._require_idle(
                "Authorized multi-account snapshot read left an active database transaction."
            )

        return ReadAuthorizedMultiAccountPortfolioSnapshotResult(portfolio=portfolio)

    async def _require_idle(self, message: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(message)

    async def _close_active_transaction(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
