"""Public API contracts for authorized Holding rebuilds."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HoldingRebuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    created: int
    updated: int
    deleted: int
    total: int
    replayed: bool
    rebuilt_at: datetime | None
