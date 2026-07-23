from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.enums import ImportSource, ImportStatus


class ImportBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ImportSource
    filename: str = Field(min_length=1, max_length=255)
    file_size: int | None = Field(default=None, ge=0, le=1_073_741_824)
    file_encoding: str | None = Field(default=None, max_length=64)
    checksum: str = Field(min_length=64, max_length=64)

    @field_validator("filename")
    @classmethod
    def normalize_filename(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Filename must not be blank.")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("Filename must not contain path separators.")
        return normalized

    @field_validator("file_encoding")
    @classmethod
    def normalize_encoding(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @field_validator("checksum")
    @classmethod
    def normalize_checksum(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("Checksum must be a 64-character SHA-256 hexadecimal digest.")
        return normalized


class ImportBatchResponse(BaseModel):
    id: str
    account_id: str
    source: ImportSource
    filename: str
    file_size: int | None
    file_encoding: str | None
    checksum: str
    status: ImportStatus
    rows_total: int | None
    rows_imported: int | None
    rows_skipped: int | None
    created_at: datetime
    completed_at: datetime | None


class ImportUploadResponse(BaseModel):
    batch_id: str
    size: int
    checksum: str
    stored: bool
    idempotent: bool


class ImportParseResponse(BaseModel):
    batch_id: str
    status: ImportStatus
    rows_total: int
    rows_pending: int
    rows_failed: int


class ImportNormalizeResponse(BaseModel):
    batch_id: str
    status: ImportStatus
    rows_total: int
    rows_normalized: int
    rows_needs_review: int
    rows_failed: int


class ImportDeduplicateResponse(BaseModel):
    batch_id: str
    status: ImportStatus
    rows_total: int
    rows_unique: int
    rows_duplicate: int
    rows_needs_review: int
    rows_failed: int
