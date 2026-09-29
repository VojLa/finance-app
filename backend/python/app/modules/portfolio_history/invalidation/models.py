"""Validated, non-financial history invalidation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntFlag

from app.modules.canonical_state.service import CanonicalChangeKind


class HistoryDirtyReason(IntFlag):
    canonical_change = 1
    scope_change = 2


@dataclass(frozen=True, slots=True)
class CanonicalInvalidationEffect:
    account_id: str
    canonical_revision: int
    kind: CanonicalChangeKind
    entity_id: str
    financial_timestamp: datetime

    def __post_init__(self) -> None:
        if (
            type(self.account_id) is not str
            or not self.account_id
            or self.account_id != self.account_id.strip()
            or type(self.entity_id) is not str
            or not self.entity_id
            or self.entity_id != self.entity_id.strip()
            or type(self.canonical_revision) is not int
            or self.canonical_revision < 1
            or type(self.kind) is not CanonicalChangeKind
            or type(self.financial_timestamp) is not datetime
            or self.financial_timestamp.tzinfo is not None
            or self.financial_timestamp.microsecond % 1_000
        ):
            raise ValueError("Canonical history invalidation effect is invalid.")


@dataclass(frozen=True, slots=True)
class PortfolioHistoryInvalidationResult:
    affected_users: tuple[str, ...]
    inserted_receipts: int
    enqueued_jobs: int
