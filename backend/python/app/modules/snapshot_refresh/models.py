"""Public response contract for coordinated manual snapshot refresh."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.db.models.enums import SnapshotGranularity

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    populate_by_name=True,
    from_attributes=True,
)


class SnapshotRefreshAccountSelectionResponse(BaseModel):
    model_config = _MODEL_CONFIG

    account_id: str = Field(serialization_alias="accountId")
    snapshot_id: str = Field(serialization_alias="snapshotId")


class UserSnapshotRefreshRecalculateResponse(BaseModel):
    model_config = _MODEL_CONFIG

    net_worth_snapshot_id: str = Field(serialization_alias="netWorthSnapshotId")
    net_worth_status: Literal["created", "replayed"] = Field(serialization_alias="netWorthStatus")
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int = Field(serialization_alias="calculationVersion")
    accounts: tuple[SnapshotRefreshAccountSelectionResponse, ...]
    refresh_account_count: int = Field(serialization_alias="refreshAccountCount")
    reuse_only_account_count: int = Field(serialization_alias="reuseOnlyAccountCount")
    created_account_snapshot_count: int = Field(serialization_alias="createdAccountSnapshotCount")
    replayed_account_snapshot_count: int = Field(serialization_alias="replayedAccountSnapshotCount")
    reused_account_snapshot_count: int = Field(serialization_alias="reusedAccountSnapshotCount")
    selected_account_snapshot_count: int = Field(serialization_alias="selectedAccountSnapshotCount")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
