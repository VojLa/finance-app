"""Snapshot-backed portfolio presentation and exact read contracts."""

from app.modules.portfolio_snapshot.aggregate_models import (
    MultiAccountPortfolioAccountView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.aggregation import (
    MultiAccountPortfolioProjectionError,
    build_multi_account_portfolio_view,
)
from app.modules.portfolio_snapshot.authorized_service import (
    AuthorizedPortfolioSnapshotService,
    PortfolioSnapshotUnavailableError,
    ReadAuthorizedPortfolioSnapshotCommand,
    ReadAuthorizedPortfolioSnapshotResult,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.projection import (
    PortfolioSnapshotProjectionError,
    build_portfolio_snapshot_view,
)
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    PortfolioSnapshotReader,
    PortfolioSnapshotReadError,
    ReadExactPortfolioSnapshotCommand,
)

__all__ = [
    "AccountType",
    "AssetType",
    "AuthorizedPortfolioSnapshotService",
    "CompletePortfolioSnapshotRead",
    "MultiAccountPortfolioAccountView",
    "MultiAccountPortfolioProjectionError",
    "MultiAccountPortfolioSummary",
    "MultiAccountPortfolioView",
    "PortfolioAccountView",
    "PortfolioPositionView",
    "PortfolioSnapshotItemSource",
    "PortfolioSnapshotProjectionError",
    "PortfolioSnapshotReadError",
    "PortfolioSnapshotReader",
    "PortfolioSnapshotSource",
    "PortfolioSnapshotUnavailableError",
    "PortfolioSnapshotView",
    "PortfolioSummaryView",
    "ReadAuthorizedPortfolioSnapshotCommand",
    "ReadAuthorizedPortfolioSnapshotResult",
    "ReadExactPortfolioSnapshotCommand",
    "SnapshotGranularity",
    "SnapshotSource",
    "build_multi_account_portfolio_view",
    "build_portfolio_snapshot_view",
]
