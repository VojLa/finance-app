from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.canonical_lineage import AccountCanonicalChangeModel
from app.db.models.common import TIMESTAMP
from app.modules.canonical_state.repository import CanonicalStateRepository

_BIGINT_MAX = 9_223_372_036_854_775_807
_MESSAGE = "Canonical account state is unavailable."


class CanonicalStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_MESSAGE)


class CanonicalChangeKind(StrEnum):
    transaction = "transaction"
    investment_event = "investment_event"
    liability_balance = "liability_balance"


@dataclass(frozen=True, slots=True)
class RecordedCanonicalChange:
    account_id: str
    revision: int
    kind: CanonicalChangeKind
    entity_id: str
    financial_timestamp: datetime
    created_at: datetime
    created: bool


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise CanonicalStateError()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise CanonicalStateError()
    return value


def _matches(
    persisted: AccountCanonicalChangeModel,
    *,
    account_id: str,
    kind: CanonicalChangeKind,
    entity_id: str,
    financial_timestamp: datetime,
    created_at: datetime,
) -> bool:
    return (
        persisted.account_id == account_id
        and persisted.kind == kind.value
        and persisted.entity_id == entity_id
        and persisted.financial_timestamp == financial_timestamp
        and persisted.created_at == created_at
        and isinstance(persisted.revision, int)
        and not isinstance(persisted.revision, bool)
        and 0 < persisted.revision <= _BIGINT_MAX
    )


class CanonicalStateService:
    """Allocate commit-ordered per-account revisions inside a caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: CanonicalStateRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or CanonicalStateRepository(session)

    async def record(
        self,
        *,
        account_id: str,
        kind: CanonicalChangeKind,
        entity_id: str,
        financial_timestamp: datetime,
        created_at: datetime,
        replay: bool,
    ) -> RecordedCanonicalChange:
        if not self.session.in_transaction() or not isinstance(kind, CanonicalChangeKind):
            raise CanonicalStateError()
        canonical_account = _text(account_id)
        canonical_entity = _text(entity_id)
        canonical_financial = _timestamp(financial_timestamp)
        canonical_created = _timestamp(created_at)
        state = await self.repository.lock_state(canonical_account)
        if (
            state is None
            or state.account_id != canonical_account
            or not isinstance(state.last_revision, int)
            or isinstance(state.last_revision, bool)
            or not 0 <= state.last_revision <= _BIGINT_MAX
            or not isinstance(state.last_investment_revision, int)
            or isinstance(state.last_investment_revision, bool)
            or not 0 <= state.last_investment_revision <= state.last_revision
            or (
                state.holding_revision is not None
                and (
                    not isinstance(state.holding_revision, int)
                    or isinstance(state.holding_revision, bool)
                    or not 0 <= state.holding_revision <= state.last_investment_revision
                )
            )
        ):
            raise CanonicalStateError()

        existing = await self.repository.load_change_by_entity(
            kind=kind.value, entity_id=canonical_entity
        )
        if replay:
            if existing is None or not _matches(
                existing,
                account_id=canonical_account,
                kind=kind,
                entity_id=canonical_entity,
                financial_timestamp=canonical_financial,
                created_at=canonical_created,
            ):
                raise CanonicalStateError()
            at_revision = await self.repository.load_change_by_revision(
                account_id=canonical_account, revision=existing.revision
            )
            if at_revision is None or at_revision.entity_id != existing.entity_id:
                raise CanonicalStateError()
            return RecordedCanonicalChange(
                account_id=canonical_account,
                revision=existing.revision,
                kind=kind,
                entity_id=canonical_entity,
                financial_timestamp=canonical_financial,
                created_at=canonical_created,
                created=False,
            )

        if existing is not None or state.last_revision >= _BIGINT_MAX:
            raise CanonicalStateError()
        revision = state.last_revision + 1
        if (
            await self.repository.load_change_by_revision(
                account_id=canonical_account, revision=revision
            )
            is not None
        ):
            raise CanonicalStateError()
        change = AccountCanonicalChangeModel(
            account_id=canonical_account,
            revision=revision,
            kind=kind.value,
            entity_id=canonical_entity,
            financial_timestamp=canonical_financial,
            created_at=canonical_created,
        )
        self.repository.add_change(change)
        state.last_revision = revision
        if kind is CanonicalChangeKind.investment_event:
            state.last_investment_revision = revision
        state.updated_at = canonical_created
        await self.repository.flush()
        return RecordedCanonicalChange(
            account_id=canonical_account,
            revision=revision,
            kind=kind,
            entity_id=canonical_entity,
            financial_timestamp=canonical_financial,
            created_at=canonical_created,
            created=True,
        )
