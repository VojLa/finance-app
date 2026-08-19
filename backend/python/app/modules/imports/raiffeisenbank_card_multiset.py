"""Pure, replayable multiset planning for Raiffeisenbank credit-card exports.

Credit-card statements do not provide a provider transaction identifier.  Their
old fallback identity therefore cannot distinguish two legitimate, otherwise
identical purchases in one export from the same purchase repeated by an
overlapping export.  This module deliberately stops before persistence: it
turns parser-attested and normalized rows into a deterministic occurrence plan
which a database-backed deduplication boundary can apply later.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.modules.imports.raiffeisenbank import (
    STATEMENT_KIND_FIELD,
    normalize_raiffeisenbank_import_row,
)


class RaiffeisenbankCardMultisetEvidenceError(ValueError):
    """Raised when evidence cannot safely participate in card multiset planning."""


@dataclass(frozen=True)
class RaiffeisenbankCardCandidate:
    """One parser-attested, already-normalized physical card row.

    ``row_number`` is audit evidence only.  It can select a deterministic
    representative among indistinguishable rows, but is never part of either
    a fingerprint or a deduplication key.
    """

    batch_id: str
    row_id: str
    row_number: int
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any]


@dataclass(frozen=True)
class RaiffeisenbankCardOccurrence:
    """One canonical occurrence and any same-occurrence export duplicates."""

    fingerprint: str
    occurrence_ordinal: int
    deduplication_key: str
    canonical_batch_id: str
    canonical_row_id: str
    canonical_row_number: int
    duplicate_row_ids: tuple[str, ...]


@dataclass(frozen=True)
class RaiffeisenbankCardMultisetPlan:
    """Persistence-ready, deterministic result for all selected card batches."""

    occurrences: tuple[RaiffeisenbankCardOccurrence, ...]

    @property
    def physical_row_count(self) -> int:
        return sum(1 + len(occurrence.duplicate_row_ids) for occurrence in self.occurrences)

    @property
    def canonical_row_count(self) -> int:
        return len(self.occurrences)

    @property
    def canonical_row_ids(self) -> tuple[str, ...]:
        return tuple(occurrence.canonical_row_id for occurrence in self.occurrences)

    @property
    def duplicate_row_ids(self) -> tuple[str, ...]:
        return tuple(
            row_id for occurrence in self.occurrences for row_id in occurrence.duplicate_row_ids
        )


def raiffeisenbank_card_full_fingerprint(*, raw_data: dict[str, Any]) -> str:
    """Hash every parser-provided source field for one card transaction.

    Header ordering and dictionary insertion order cannot influence this value.
    The internal statement-kind marker is represented separately so it remains
    part of the evidence without becoming an accidental source-column name.
    """
    source_fields = _validated_card_raw_data(raw_data)
    identity = {
        "schema_version": 1,
        "source": "raiffeisenbank",
        "statement_kind": "card_statement",
        "source_fields": source_fields,
    }
    return _hash(identity)


def plan_raiffeisenbank_card_multiset(
    *,
    account_id: str,
    candidates: Iterable[RaiffeisenbankCardCandidate],
) -> RaiffeisenbankCardMultisetPlan:
    """Plan canonical card occurrences with cross-batch multiplicity ``max``.

    For each full source fingerprint, the canonical number of occurrences is
    the largest count observed in any one batch.  The first, second, ..., Nth
    row from every batch are aligned by their source row number, so repetitions
    within one export survive while the corresponding rows from an overlapping
    export become duplicates.  Sorting is explicit at every boundary, making
    the plan independent of input and file ordering.
    """
    _require_identifier("account_id", account_id)
    grouped: dict[str, dict[str, list[RaiffeisenbankCardCandidate]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen_row_ids: set[str] = set()
    seen_batch_rows: set[tuple[str, int]] = set()

    for candidate in candidates:
        _validate_candidate(account_id=account_id, candidate=candidate)
        if candidate.row_id in seen_row_ids:
            raise RaiffeisenbankCardMultisetEvidenceError("Card row IDs must be unique.")
        batch_row = (candidate.batch_id, candidate.row_number)
        if batch_row in seen_batch_rows:
            raise RaiffeisenbankCardMultisetEvidenceError(
                "A card batch cannot contain the same row number twice."
            )
        seen_row_ids.add(candidate.row_id)
        seen_batch_rows.add(batch_row)
        fingerprint = raiffeisenbank_card_full_fingerprint(raw_data=candidate.raw_data)
        grouped[fingerprint][candidate.batch_id].append(candidate)

    occurrences: list[RaiffeisenbankCardOccurrence] = []
    for fingerprint in sorted(grouped):
        batch_groups = grouped[fingerprint]
        ordered_batches = {
            batch_id: sorted(rows, key=lambda row: (row.row_number, row.row_id))
            for batch_id, rows in batch_groups.items()
        }
        multiplicity = max(len(rows) for rows in ordered_batches.values())
        for ordinal in range(1, multiplicity + 1):
            members = [
                rows[ordinal - 1] for rows in ordered_batches.values() if len(rows) >= ordinal
            ]
            canonical = min(
                members,
                key=lambda row: (row.batch_id, row.row_number, row.row_id),
            )
            duplicates = tuple(
                row.row_id
                for row in sorted(
                    members, key=lambda row: (row.batch_id, row.row_number, row.row_id)
                )
                if row.row_id != canonical.row_id
            )
            occurrences.append(
                RaiffeisenbankCardOccurrence(
                    fingerprint=fingerprint,
                    occurrence_ordinal=ordinal,
                    deduplication_key=_occurrence_key(
                        account_id=account_id,
                        fingerprint=fingerprint,
                        occurrence_ordinal=ordinal,
                    ),
                    canonical_batch_id=canonical.batch_id,
                    canonical_row_id=canonical.row_id,
                    canonical_row_number=canonical.row_number,
                    duplicate_row_ids=duplicates,
                )
            )
    return RaiffeisenbankCardMultisetPlan(occurrences=tuple(occurrences))


def _validate_candidate(*, account_id: str, candidate: RaiffeisenbankCardCandidate) -> None:
    _require_identifier("batch_id", candidate.batch_id)
    _require_identifier("row_id", candidate.row_id)
    if isinstance(candidate.row_number, bool) or not isinstance(candidate.row_number, int):
        raise RaiffeisenbankCardMultisetEvidenceError("Card row number must be an integer.")
    if candidate.row_number < 1:
        raise RaiffeisenbankCardMultisetEvidenceError("Card row number must be positive.")
    _validated_card_raw_data(candidate.raw_data)
    expected = normalize_raiffeisenbank_import_row(
        account_id=account_id,
        raw_data=candidate.raw_data,
    )
    if (
        expected.data is None
        or expected.deduplication_key is None
        or expected.validation_errors is not None
        or candidate.normalized_data != expected.data
    ):
        raise RaiffeisenbankCardMultisetEvidenceError(
            "Card normalized evidence does not exactly match its parser evidence."
        )


def _validated_card_raw_data(raw_data: dict[str, Any]) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(raw_data, dict):
        raise RaiffeisenbankCardMultisetEvidenceError("Card source evidence must be a dictionary.")
    if raw_data.get(STATEMENT_KIND_FIELD) != "card_statement":
        raise RaiffeisenbankCardMultisetEvidenceError(
            "Card source evidence has an invalid statement kind."
        )
    source_fields: list[tuple[str, str | None]] = []
    for field, value in raw_data.items():
        if not isinstance(field, str) or not field.strip():
            raise RaiffeisenbankCardMultisetEvidenceError(
                "Card source field names must be non-empty strings."
            )
        if field == STATEMENT_KIND_FIELD:
            continue
        if field.startswith("__"):
            raise RaiffeisenbankCardMultisetEvidenceError(
                "Card source evidence contains parser errors."
            )
        if value is not None and not isinstance(value, str):
            raise RaiffeisenbankCardMultisetEvidenceError(
                "Card source field values must be strings or null."
            )
        source_fields.append((field, value))
    if not source_fields:
        raise RaiffeisenbankCardMultisetEvidenceError("Card source evidence has no source fields.")
    return tuple(sorted(source_fields))


def _require_identifier(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RaiffeisenbankCardMultisetEvidenceError(
            f"Card {name} must be a non-empty identifier."
        )


def _occurrence_key(*, account_id: str, fingerprint: str, occurrence_ordinal: int) -> str:
    return _hash(
        {
            "schema_version": 1,
            "source": "raiffeisenbank",
            "account_id": account_id,
            "statement_kind": "card_statement",
            "fingerprint": fingerprint,
            "occurrence_ordinal": occurrence_ordinal,
        }
    )


def _hash(identity: dict[str, Any]) -> str:
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
