from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus

JOB_SCHEMA_VERSION: Final[Literal[1]] = 1
MAX_IMPORT_JOB_BATCHES = 10


class ImportJobPhase(StrEnum):
    queued = "queued"
    parsing = "parsing"
    normalizing = "normalizing"
    deduplicating = "deduplicating"
    classifying = "classifying"
    posting = "posting"
    reconciling = "reconciling"
    acquiring_reporting_fx = "acquiring_reporting_fx"
    validating_liability = "validating_liability"
    rebuilding_holdings = "rebuilding_holdings"
    refreshing_snapshot = "refreshing_snapshot"
    completed = "completed"


class ImportJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = JOB_SCHEMA_VERSION
    batch_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_IMPORT_JOB_BATCHES)

    @field_validator("batch_ids")
    @classmethod
    def validate_batch_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item != item.strip() or len(item) > 255 for item in value):
            raise ValueError("Batch IDs must be bounded canonical strings.")
        if tuple(sorted(set(value))) != value:
            raise ValueError("Batch IDs must be unique and sorted.")
        return value


class ImportJobCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = JOB_SCHEMA_VERSION
    phase: ImportJobPhase = ImportJobPhase.queued
    completed_batch_ids: tuple[str, ...] = Field(default=(), max_length=MAX_IMPORT_JOB_BATCHES)

    @field_validator("completed_batch_ids")
    @classmethod
    def validate_completed_batch_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item != item.strip() or len(item) > 255 for item in value):
            raise ValueError("Completed batch IDs must be bounded canonical strings.")
        if tuple(sorted(set(value))) != value:
            raise ValueError("Completed batch IDs must be unique and sorted.")
        return value


class ImportJobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = JOB_SCHEMA_VERSION
    phase: ImportJobPhase
    completed_units: int = Field(ge=0, le=1_000_000_000)
    total_units: int = Field(ge=1, le=1_000_000_000)
    completed_batches: int = Field(ge=0, le=MAX_IMPORT_JOB_BATCHES)
    total_batches: int = Field(ge=1, le=MAX_IMPORT_JOB_BATCHES)

    @model_validator(mode="after")
    def validate_counters(self) -> ImportJobProgress:
        if self.completed_units > self.total_units:
            raise ValueError("Completed units cannot exceed total units.")
        if self.completed_batches > self.total_batches:
            raise ValueError("Completed batches cannot exceed total batches.")
        return self


class ImportJobResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = JOB_SCHEMA_VERSION
    batch_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_IMPORT_JOB_BATCHES)
    rows_total: int = Field(ge=0, le=1_000_000_000)
    rows_imported: int = Field(ge=0, le=1_000_000_000)
    rows_skipped: int = Field(ge=0, le=1_000_000_000)
    snapshot_refresh_status: Literal["created", "replayed", "not_required"]
    completed_at: datetime

    @field_validator("batch_ids")
    @classmethod
    def validate_batch_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return ImportJobPayload(batch_ids=value).batch_ids

    @model_validator(mode="after")
    def validate_rows(self) -> ImportJobResult:
        if self.rows_imported + self.rows_skipped != self.rows_total:
            raise ValueError("Imported and skipped rows must exactly match total rows.")
        if self.completed_at.tzinfo is not None:
            raise ValueError("Persisted job timestamps must be timezone-naive UTC.")
        return self


class ImportJobStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_IMPORT_JOB_BATCHES)

    @field_validator("batch_ids")
    @classmethod
    def validate_batch_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return ImportJobPayload(batch_ids=value).batch_ids


class ImportJobError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=100, pattern=r"^[^\r\n]+$")
    message: str = Field(min_length=1, max_length=1000, pattern=r"^[^\r\n]+$")


class ImportJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    account_id: str
    kind: BackgroundJobKind
    status: BackgroundJobStatus
    progress: ImportJobProgress
    result: ImportJobResult | None
    error: ImportJobError | None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    manual_retry_count: int = Field(ge=0)
    run_after: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def canonical_import_job_idempotency_key(
    *,
    user_id: str,
    account_id: str,
    batch_ids: tuple[str, ...],
) -> str:
    if not user_id or user_id != user_id.strip() or len(user_id) > 255:
        raise ValueError("User ID must be a bounded canonical string.")
    if not account_id or account_id != account_id.strip() or len(account_id) > 255:
        raise ValueError("Account ID must be a bounded canonical string.")
    if len(set(batch_ids)) != len(batch_ids):
        raise ValueError("Batch IDs must be unique.")
    canonical_batches = tuple(sorted(batch_ids))
    payload = ImportJobPayload(batch_ids=canonical_batches)
    digest_input = "\0".join(
        (
            "v1",
            "import_workflow",
            user_id,
            account_id,
            *payload.batch_ids,
        )
    )
    return sha256(digest_input.encode("utf-8")).hexdigest()
