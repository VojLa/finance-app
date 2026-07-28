"""Public response contracts for manual account snapshots."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.db.models.enums import SnapshotGranularity


class AccountSnapshotRecalculateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    snapshot_id: str = Field(serialization_alias="snapshotId")
    account_id: str = Field(serialization_alias="accountId")
    status: Literal["created", "replayed"]
    item_count: int = Field(serialization_alias="itemCount")
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
