"""Pure dashboard projection from an exact multi-account portfolio snapshot."""

from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
    ReadAuthorizedDashboardSnapshotResult,
)
from app.modules.dashboard_snapshot.models import (
    DashboardAccountCard,
    DashboardAssetTypeAllocation,
    DashboardSnapshotSummary,
    DashboardSnapshotView,
    DashboardTopPosition,
)
from app.modules.dashboard_snapshot.projection import (
    DashboardSnapshotProjectionError,
    build_dashboard_snapshot_view,
)

__all__ = [
    "AuthorizedDashboardSnapshotService",
    "DashboardAccountCard",
    "DashboardAssetTypeAllocation",
    "DashboardSnapshotProjectionError",
    "DashboardSnapshotSummary",
    "DashboardSnapshotView",
    "DashboardTopPosition",
    "ReadAuthorizedDashboardSnapshotResult",
    "build_dashboard_snapshot_view",
]
