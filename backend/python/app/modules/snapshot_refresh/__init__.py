"""Cross-domain contracts for coordinated snapshot refreshes."""

from app.modules.snapshot_refresh.evidence_service import (
    BuildSnapshotRefreshCoverageCommand,
    CompleteSnapshotRefreshCoverage,
    SelectedReusableAccountSnapshot,
    SnapshotRefreshEvidenceService,
    SnapshotRefreshEvidenceStateError,
)
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshot_refresh.executor_repository import (
    SnapshotRefreshExecutorRepository,
)
from app.modules.snapshot_refresh.manual_service import (
    CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION,
    MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY,
    MANUAL_USER_SNAPSHOT_REFRESH_SOURCE,
    ManualUserSnapshotRefreshService,
    RecalculateUserSnapshotRefreshCommand,
    RecalculateUserSnapshotRefreshResult,
    UserSnapshotRefreshConflictError,
    UserSnapshotRefreshUnavailableError,
    canonical_manual_user_snapshot_refresh_bucket,
    current_user_snapshot_refresh_timestamp,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshot_refresh.models import (
    UserSnapshotRefreshRecalculateResponse,
)
from app.modules.snapshot_refresh.plan import (
    AccountSnapshotRefreshMode,
    ExpectedAccountSnapshotRefreshTarget,
    ExpectedNetWorthRefreshTarget,
    ExpectedUserSnapshotRefreshPlan,
    SnapshotRefreshAccountEvidence,
    SnapshotRefreshPlanInput,
    SnapshotRefreshPlanStateError,
    build_user_snapshot_refresh_plan,
)
from app.modules.snapshot_refresh.repository import (
    PersistedSnapshotRefreshAccess,
    SnapshotRefreshEvidenceRepository,
)

__all__ = [
    "CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION",
    "MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY",
    "MANUAL_USER_SNAPSHOT_REFRESH_SOURCE",
    "AccountSnapshotRefreshExecutionDisposition",
    "AccountSnapshotRefreshMode",
    "BuildSnapshotRefreshCoverageCommand",
    "CompleteSnapshotRefreshCoverage",
    "ExecuteMarketBackedSnapshotRefreshCommand",
    "ExecuteMarketBackedSnapshotRefreshResult",
    "ExecuteUserSnapshotRefreshCommand",
    "ExecuteUserSnapshotRefreshResult",
    "ExecutedAccountSnapshotRefresh",
    "ExpectedAccountSnapshotRefreshTarget",
    "ExpectedNetWorthRefreshTarget",
    "ExpectedUserSnapshotRefreshPlan",
    "ManualUserSnapshotRefreshService",
    "MarketBackedSnapshotRefreshConflictError",
    "MarketBackedSnapshotRefreshService",
    "MarketBackedSnapshotRefreshUnavailableError",
    "PersistedSnapshotRefreshAccess",
    "RecalculateUserSnapshotRefreshCommand",
    "RecalculateUserSnapshotRefreshResult",
    "SelectedReusableAccountSnapshot",
    "SnapshotRefreshAccountEvidence",
    "SnapshotRefreshEvidenceRepository",
    "SnapshotRefreshEvidenceService",
    "SnapshotRefreshEvidenceStateError",
    "SnapshotRefreshExecutionConflictError",
    "SnapshotRefreshExecutionStateError",
    "SnapshotRefreshExecutorRepository",
    "SnapshotRefreshPlanInput",
    "SnapshotRefreshPlanStateError",
    "UserSnapshotRefreshConflictError",
    "UserSnapshotRefreshExecutor",
    "UserSnapshotRefreshRecalculateResponse",
    "UserSnapshotRefreshUnavailableError",
    "build_user_snapshot_refresh_plan",
    "canonical_manual_user_snapshot_refresh_bucket",
    "current_user_snapshot_refresh_timestamp",
]
