"""Stable pure helpers shared by canonical import posting boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql

from app.modules.imports.normalizers import MAX_OPTIONAL_FIELD_LENGTH
from app.shared.errors import ApplicationError

DEDUPLICATION_METADATA_KEY = "deduplication"
POSTING_INTENT_METADATA_KEY = "posting_intent"
UNIQUE_DEDUPLICATION_MARKER = {"schema_version": 1, "status": "unique"}


class ImportPostStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_post_state_invalid",
            message="The import batch is not available for posting.",
            status_code=409,
        )


def copied_canonical_payload(normalized_data: Mapping[str, Any]) -> dict[str, Any]:
    canonical = deepcopy(dict(normalized_data))
    canonical.pop(DEDUPLICATION_METADATA_KEY, None)
    canonical.pop(POSTING_INTENT_METADATA_KEY, None)
    return canonical


def bounded_optional_text(
    value: object,
    *,
    maximum_length: int = MAX_OPTIONAL_FIELD_LENGTH,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum_length:
        raise ImportPostStateError()
    return value


def exact_numeric(value: Decimal, contract: Numeric[Any]) -> Decimal:
    precision = contract.precision
    scale = contract.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric type must define precision and scale.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        scaled = value.quantize(quantum)
    except InvalidOperation as exc:
        raise ImportPostStateError() from exc
    limit = Decimal(10) ** (precision - scale)
    if not value.is_finite() or value != scaled or abs(value) >= limit:
        raise ImportPostStateError()
    return value


def exact_naive_timestamp(
    value: str,
    contract: postgresql.TIMESTAMP,
) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            if parsed_date.isoformat() != value:
                raise ImportPostStateError()
            result = datetime.combine(parsed_date, datetime.min.time())
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.isoformat() != value:
                raise ImportPostStateError()
            result = (
                parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)
            )
    except (TypeError, ValueError) as exc:
        raise ImportPostStateError() from exc
    precision = contract.precision
    if precision is not None:
        unit = 10 ** (6 - precision)
        if result.microsecond % unit:
            raise ImportPostStateError()
    return result
