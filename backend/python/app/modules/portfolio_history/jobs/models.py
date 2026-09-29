"""Strict, non-financial wire contracts for durable history jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import SnapshotSeriesJobKind

HISTORY_JOB_SCHEMA_VERSION: Final[Literal[1]] = 1


class PortfolioHistoryJobPhase(StrEnum):
    queued = "queued"
    replaying = "replaying"
    capturing = "capturing"
    completed = "completed"


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*")
    @classmethod
    def validate_persisted_timestamp(cls, value: object) -> object:
        if isinstance(value, datetime) and (value.tzinfo is not None or value.microsecond % 1_000):
            raise ValueError("Persisted history-job timestamps must be naive UTC milliseconds.")
        return value


class HistoryRebuildPayload(_WireModel):
    schema_version: Literal[1] = HISTORY_JOB_SCHEMA_VERSION
    dirty_epoch: int = Field(ge=1)
    dirty_from: datetime


class HistoryCapturePayload(_WireModel):
    schema_version: Literal[1] = HISTORY_JOB_SCHEMA_VERSION
    capture_at: datetime


type PortfolioHistoryJobPayload = HistoryRebuildPayload | HistoryCapturePayload


class PortfolioHistoryPublicationRetirementReceipt(_WireModel):
    """Bounded crash-safe evidence that an empty user scope retired its pointer."""

    reason: Literal["empty_scope"] = "empty_scope"
    retired_at: datetime
    generation_id: str | None = Field(default=None, min_length=1, max_length=500)
    publication_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_publication_fence(self) -> PortfolioHistoryPublicationRetirementReceipt:
        if (self.generation_id is None) != (self.publication_version is None):
            raise ValueError("History retirement publication fence is incomplete.")
        return self


class PortfolioHistoryJobCheckpoint(_WireModel):
    schema_version: Literal[1] = HISTORY_JOB_SCHEMA_VERSION
    phase: PortfolioHistoryJobPhase = PortfolioHistoryJobPhase.queued
    completed_units: int = Field(default=0, ge=0, le=1_000_000_000)
    generation_id: str | None = Field(default=None, min_length=1, max_length=500)
    covered_through: datetime | None = None
    retirement: PortfolioHistoryPublicationRetirementReceipt | None = None

    @model_validator(mode="after")
    def validate_generation_fence(self) -> PortfolioHistoryJobCheckpoint:
        if (self.generation_id is None) != (self.covered_through is None):
            raise ValueError("History generation checkpoint fence is incomplete.")
        if self.retirement is not None and self.generation_id is not None:
            raise ValueError("History retirement cannot expose a private generation fence.")
        return self


class PortfolioHistoryJobProgress(_WireModel):
    schema_version: Literal[1] = HISTORY_JOB_SCHEMA_VERSION
    phase: PortfolioHistoryJobPhase
    completed_units: int = Field(ge=0, le=1_000_000_000)
    total_units: int = Field(ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_counts(self) -> PortfolioHistoryJobProgress:
        if self.completed_units > self.total_units:
            raise ValueError("Completed units cannot exceed total units.")
        return self


class PortfolioHistoryJobResult(_WireModel):
    schema_version: Literal[1] = HISTORY_JOB_SCHEMA_VERSION
    completed_at: datetime
    outcome: Literal["completed", "no_work"]
    retirement: PortfolioHistoryPublicationRetirementReceipt | None = None

    @model_validator(mode="after")
    def validate_outcome_evidence(self) -> PortfolioHistoryJobResult:
        if self.retirement is not None and self.outcome != "no_work":
            raise ValueError("History retirement must complete as no work.")
        return self


class PortfolioHistoryJobError(_WireModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[^\r\n]+$")
    message: str = Field(min_length=1, max_length=1000, pattern=r"^[^\r\n]+$")

    @field_validator("message")
    @classmethod
    def redact_financial_payload(cls, value: str) -> str:
        # Durable failures are public operational state.  Do not turn raw
        # provider/ledger payloads into an accidental financial data store.
        if any(token in value.lower() for token in ("price", "amount", "balance", "transaction")):
            raise ValueError("History job error messages must be generic.")
        return value


def validate_history_payload(
    kind: SnapshotSeriesJobKind, value: object
) -> PortfolioHistoryJobPayload:
    mapping: dict[SnapshotSeriesJobKind, Any] = {
        SnapshotSeriesJobKind.rebuild: HistoryRebuildPayload,
        SnapshotSeriesJobKind.capture: HistoryCapturePayload,
    }
    try:
        return cast(PortfolioHistoryJobPayload, mapping[kind].model_validate(value))
    except (KeyError, ValueError) as exc:
        raise ValueError("The history job payload does not match its kind.") from exc


def canonical_history_job_idempotency_key(
    *, user_id: str, kind: SnapshotSeriesJobKind, payload: PortfolioHistoryJobPayload
) -> str:
    if (
        not isinstance(user_id, str)
        or not user_id
        or user_id != user_id.strip()
        or len(user_id) > 255
    ):
        raise ValueError("User ID must be a bounded canonical string.")
    digest_input = "\0".join(
        ("v1", kind.value, user_id, payload.model_dump_json(exclude_none=True))
    )
    return sha256(digest_input.encode("utf-8")).hexdigest()
