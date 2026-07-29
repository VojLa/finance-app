"""Public request and response contracts for manual account snapshots."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.db.models.enums import SnapshotGranularity


class AccountSnapshotRecalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_currency: str | None = Field(default=None, alias="outputCurrency")

    @field_validator("output_currency", mode="before")
    @classmethod
    def validate_output_currency(cls, value: object) -> object:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or len(value) != 3
            or not value.isascii()
            or not value.isalpha()
            or value != value.upper()
        ):
            raise ValueError("Output currency must be three uppercase ASCII letters.")
        return value


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
