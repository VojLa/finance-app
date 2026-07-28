"""Net-worth domain, persistence, and manual orchestration contracts."""

from app.modules.net_worth.manual_service import (
    CURRENT_NET_WORTH_CALCULATION_VERSION,
    ManualNetWorthSnapshotService,
    NetWorthSnapshotConflictError,
    NetWorthSnapshotUnavailableError,
    RecalculateNetWorthSnapshotCommand,
    RecalculateNetWorthSnapshotResult,
)
from app.modules.net_worth.persistence_projection import (
    CanonicalNetWorthJsonObject,
    ExpectedNetWorthSnapshotPersistence,
    ExpectedNetWorthSnapshotRow,
    NetWorthSnapshotPersistenceAudit,
    NetWorthSnapshotPersistenceMetadata,
    NetWorthSnapshotPersistenceProjectionError,
    build_net_worth_snapshot_persistence_projection,
)
from app.modules.net_worth.projection import (
    AccountNetWorthEvidence,
    ExpectedNetWorthAccountContribution,
    ExpectedNetWorthProjection,
    NetWorthAccountTypeAmount,
    NetWorthCurrencyAmount,
    NetWorthProjectionInput,
    NetWorthProjectionStateError,
    build_net_worth_projection,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriteDisposition,
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)

__all__ = [
    "CURRENT_NET_WORTH_CALCULATION_VERSION",
    "AccountNetWorthEvidence",
    "CanonicalNetWorthJsonObject",
    "ExpectedNetWorthAccountContribution",
    "ExpectedNetWorthProjection",
    "ExpectedNetWorthSnapshotPersistence",
    "ExpectedNetWorthSnapshotRow",
    "ManualNetWorthSnapshotService",
    "NetWorthAccountTypeAmount",
    "NetWorthCurrencyAmount",
    "NetWorthProjectionInput",
    "NetWorthProjectionStateError",
    "NetWorthSnapshotConflictError",
    "NetWorthSnapshotPersistenceAudit",
    "NetWorthSnapshotPersistenceMetadata",
    "NetWorthSnapshotPersistenceProjectionError",
    "NetWorthSnapshotUnavailableError",
    "NetWorthSnapshotWriteConflictError",
    "NetWorthSnapshotWriteDisposition",
    "NetWorthSnapshotWriteResult",
    "NetWorthSnapshotWriteStateError",
    "NetWorthSnapshotWriter",
    "RecalculateNetWorthSnapshotCommand",
    "RecalculateNetWorthSnapshotResult",
    "WriteNetWorthSnapshotCommand",
    "build_net_worth_projection",
    "build_net_worth_snapshot_persistence_projection",
]
