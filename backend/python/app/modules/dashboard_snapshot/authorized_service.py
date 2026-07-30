"""Thin authorized application service for one exact dashboard snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.dashboard_snapshot.models import DashboardSnapshotView
from app.modules.dashboard_snapshot.projection import (
    DashboardSnapshotProjectionError,
    build_dashboard_snapshot_view,
)
from app.modules.portfolio_snapshot.aggregate_models import MultiAccountPortfolioView
from app.modules.portfolio_snapshot.authorized_reader import (
    PortfolioSnapshotUnavailableError,
    portfolio_snapshot_unavailable,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ReadAuthorizedMultiAccountPortfolioSnapshotResult,
)


@dataclass(frozen=True, slots=True)
class ReadAuthorizedDashboardSnapshotResult:
    """Public-safe exact dashboard snapshot."""

    dashboard: DashboardSnapshotView


class _PortfolioService(Protocol):
    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedMultiAccountPortfolioSnapshotResult: ...


type DashboardBuilder = Callable[[MultiAccountPortfolioView], DashboardSnapshotView]


class AuthorizedDashboardSnapshotService:
    """Compose the authorized portfolio service with the sole dashboard projection."""

    def __init__(
        self,
        portfolio_service: _PortfolioService,
        *,
        dashboard_builder: DashboardBuilder = build_dashboard_snapshot_view,
    ) -> None:
        self.portfolio_service = portfolio_service
        self.dashboard_builder = dashboard_builder

    async def read(
        self,
        command: ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ) -> ReadAuthorizedDashboardSnapshotResult:
        try:
            result = await self.portfolio_service.read(command)
            if type(result) is not ReadAuthorizedMultiAccountPortfolioSnapshotResult:
                raise portfolio_snapshot_unavailable()
            dashboard = self.dashboard_builder(result.portfolio)
            if type(dashboard) is not DashboardSnapshotView:
                raise portfolio_snapshot_unavailable()
            return ReadAuthorizedDashboardSnapshotResult(dashboard=dashboard)
        except (AccountNotFoundError, AccountAccessDeniedError):
            raise
        except PortfolioSnapshotUnavailableError:
            raise
        except (DashboardSnapshotProjectionError, AttributeError, TypeError, ValueError) as exc:
            raise portfolio_snapshot_unavailable() from exc
