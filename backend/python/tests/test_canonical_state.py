from datetime import datetime
from typing import Any, cast

import pytest

from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.modules.canonical_state import (
    CanonicalChangeKind,
    CanonicalStateError,
    CanonicalStateService,
    RecordedCanonicalChange,
)

AT = datetime(2026, 8, 8, 10, 0, 0, 123000)
CREATED_AT = datetime(2026, 8, 8, 10, 1, 0, 456000)


class _Session:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active

    def in_transaction(self) -> bool:
        return self.active


class _Repository:
    def __init__(self) -> None:
        self.state = AccountCanonicalStateModel(
            account_id="account-1",
            last_revision=0,
            last_investment_revision=0,
            holding_revision=None,
            updated_at=CREATED_AT,
        )
        self.changes: dict[tuple[str, int], AccountCanonicalChangeModel] = {}
        self.entities: dict[tuple[str, str], AccountCanonicalChangeModel] = {}
        self.flush_count = 0

    async def lock_state(self, account_id: str) -> AccountCanonicalStateModel | None:
        return self.state if account_id == self.state.account_id else None

    async def load_change_by_entity(
        self, *, kind: str, entity_id: str
    ) -> AccountCanonicalChangeModel | None:
        return self.entities.get((kind, entity_id))

    async def load_change_by_revision(
        self, *, account_id: str, revision: int
    ) -> AccountCanonicalChangeModel | None:
        return self.changes.get((account_id, revision))

    def add_change(self, change: AccountCanonicalChangeModel) -> None:
        self.changes[(change.account_id, change.revision)] = change
        self.entities[(change.kind, change.entity_id)] = change

    async def flush(self) -> None:
        self.flush_count += 1


def _service(repository: _Repository, *, active: bool = True) -> CanonicalStateService:
    return CanonicalStateService(
        cast(Any, _Session(active=active)), repository=cast(Any, repository)
    )


async def _record(
    service: CanonicalStateService,
    *,
    entity_id: str,
    kind: CanonicalChangeKind = CanonicalChangeKind.transaction,
    replay: bool = False,
) -> RecordedCanonicalChange:
    return await service.record(
        account_id="account-1",
        kind=kind,
        entity_id=entity_id,
        financial_timestamp=AT,
        created_at=CREATED_AT,
        replay=replay,
    )


@pytest.mark.asyncio
async def test_committed_order_allocates_exact_monotonic_revisions() -> None:
    repository = _Repository()
    service = _service(repository)

    first = await _record(service, entity_id="transaction-1")
    second = await _record(service, entity_id="transaction-2")

    assert first.revision == 1
    assert second.revision == 2
    assert repository.state.last_revision == 2
    assert tuple(repository.changes) == (("account-1", 1), ("account-1", 2))


@pytest.mark.asyncio
async def test_exact_replay_validates_journal_without_increment() -> None:
    repository = _Repository()
    service = _service(repository)
    await _record(service, entity_id="transaction-1")

    replay = await _record(service, entity_id="transaction-1", replay=True)

    assert replay.created is False
    assert replay.revision == 1
    assert repository.state.last_revision == 1
    assert repository.flush_count == 1


@pytest.mark.asyncio
async def test_one_event_with_movements_is_one_investment_revision() -> None:
    repository = _Repository()
    service = _service(repository)

    result = await _record(
        service,
        entity_id="event-1",
        kind=CanonicalChangeKind.investment_event,
    )

    assert result.revision == 1
    assert repository.state.last_investment_revision == 1
    assert repository.state.holding_revision is None


@pytest.mark.asyncio
async def test_noninvestment_revision_does_not_advance_investment_watermark() -> None:
    repository = _Repository()
    service = _service(repository)
    await _record(
        service,
        entity_id="event-1",
        kind=CanonicalChangeKind.investment_event,
    )
    repository.state.holding_revision = 1

    await _record(service, entity_id="transaction-1")

    assert repository.state.last_revision == 2
    assert repository.state.last_investment_revision == 1
    assert repository.state.holding_revision == 1


@pytest.mark.asyncio
async def test_missing_transaction_and_corrupt_replay_fail_closed() -> None:
    repository = _Repository()
    service = _service(repository)

    with pytest.raises(CanonicalStateError):
        await _record(service, entity_id="missing", replay=True)

    await _record(service, entity_id="transaction-1")
    repository.changes[("account-1", 1)].financial_timestamp = datetime(2026, 8, 7)
    with pytest.raises(CanonicalStateError):
        await _record(service, entity_id="transaction-1", replay=True)


@pytest.mark.asyncio
async def test_missing_state_inactive_transaction_and_overflow_fail_closed() -> None:
    repository = _Repository()
    repository.state.account_id = "other"
    with pytest.raises(CanonicalStateError):
        await _record(_service(repository), entity_id="transaction-1")

    repository.state.account_id = "account-1"
    with pytest.raises(CanonicalStateError):
        await _record(_service(repository, active=False), entity_id="transaction-1")

    repository.state.last_revision = 9_223_372_036_854_775_807
    with pytest.raises(CanonicalStateError):
        await _record(_service(repository), entity_id="transaction-1")


@pytest.mark.asyncio
async def test_bool_revision_and_noncanonical_timestamps_are_rejected() -> None:
    repository = _Repository()
    repository.state.last_revision = cast(Any, True)
    with pytest.raises(CanonicalStateError):
        await _record(_service(repository), entity_id="transaction-1")

    repository.state.last_revision = 0
    with pytest.raises(CanonicalStateError):
        await _service(repository).record(
            account_id="account-1",
            kind=CanonicalChangeKind.transaction,
            entity_id="transaction-1",
            financial_timestamp=datetime(2026, 8, 8, 10, 0, 0, 123456),
            created_at=CREATED_AT,
            replay=False,
        )
