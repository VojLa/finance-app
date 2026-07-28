"""Public response contracts for manual net-worth recalculation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.db.models.enums import SnapshotGranularity


class NetWorthSnapshotRecalculateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    snapshot_id: str = Field(serialization_alias="snapshotId")
    status: Literal["created", "replayed"]
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    account_count: int = Field(serialization_alias="accountCount")
    selected_account_snapshot_count: int = Field(serialization_alias="selectedAccountSnapshotCount")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
