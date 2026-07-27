"""Pure holding projection contracts."""

from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import (
    HoldingRebuildApplicationService,
    HoldingRebuildUnavailableError,
    RebuildHoldingsCommand,
)
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    HoldingPersistenceProjection,
    build_holding_persistence_projection,
)
from app.modules.holdings.projection import (
    ExpectedHoldingPlan,
    HoldingProjection,
    HoldingProjectionMovement,
    HoldingProjectionStateError,
    build_holding_projection,
)
from app.modules.holdings.rebuild_service import (
    HoldingCreatePlan,
    HoldingDeletePlan,
    HoldingRebuildPlan,
    HoldingRebuildResult,
    HoldingRebuildService,
    HoldingRebuildStateError,
    HoldingUpdatePlan,
    build_holding_rebuild_plan,
    stable_holding_id,
)

__all__ = [
    "ExpectedHoldingPlan",
    "ExpectedPersistedHoldingPlan",
    "HoldingCreatePlan",
    "HoldingDeletePlan",
    "HoldingPersistenceEvent",
    "HoldingPersistenceMovement",
    "HoldingPersistenceProjection",
    "HoldingProjection",
    "HoldingProjectionMovement",
    "HoldingProjectionStateError",
    "HoldingRebuildApplicationService",
    "HoldingRebuildPlan",
    "HoldingRebuildResponse",
    "HoldingRebuildResult",
    "HoldingRebuildService",
    "HoldingRebuildStateError",
    "HoldingRebuildUnavailableError",
    "HoldingUpdatePlan",
    "RebuildHoldingsCommand",
    "build_holding_persistence_projection",
    "build_holding_projection",
    "build_holding_rebuild_plan",
    "stable_holding_id",
]
