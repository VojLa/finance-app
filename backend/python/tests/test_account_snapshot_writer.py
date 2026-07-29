from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.accounts import AccountModel
from app.db.models.enums import (
    AccountType,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.snapshots.evidence_service import (
    BuildAccountSnapshotEvidenceCommand,
    CompleteAccountSnapshotEvidence,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceAudit,
    AccountSnapshotPersistenceMetadata,
    CanonicalJsonObject,
    ExpectedAccountSnapshotItemRow,
    ExpectedAccountSnapshotPersistence,
    ExpectedAccountSnapshotRow,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriteConflictError,
    AccountSnapshotWriteDisposition,
    AccountSnapshotWriter,
    AccountSnapshotWriteResult,
    AccountSnapshotWriteStateError,
    WriteAccountSnapshotCommand,
)
from app.modules.snapshots.writer_repository import (
    AccountSnapshotWriterRepository,
    account_snapshot_lock_scope,
)

SNAPSHOT_AT = datetime(2026, 7, 28)
CALCULATED_AT = datetime(2026, 7, 28, 0, 1)
CREATED_AT = datetime(2026, 7, 28, 0, 2)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True
        self.session.begin_count += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.session.commit_count += 1
        else:
            self.session.rollback_count += 1
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _Evidence:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.value = cast(CompleteAccountSnapshotEvidence, object())
        self.error: Exception | None = None

    async def build(self, command: object) -> CompleteAccountSnapshotEvidence:
        self.calls.append(command)
        if self.error is not None:
            raise self.error
        return self.value


class _Repository:
    def __init__(self, projection: ExpectedAccountSnapshotPersistence) -> None:
        self.account = _account()
        self.existing: AccountSnapshotModel | None = None
        self.existing_items: tuple[AccountSnapshotItemModel, ...] = ()
        self.inserted_snapshot: AccountSnapshotModel | None = None
        self.inserted_items: tuple[AccountSnapshotItemModel, ...] = ()
        self.calls: list[str] = []
        self.flush_count = 0
        self.projection = projection
        self.reload_mismatch = False
        self.flush_error: Exception | None = None
        self.snapshot_lock_values: dict[str, object] | None = None
        self.existing_values: dict[str, object] | None = None

    async def load_account_for_share(self, account_id: str) -> AccountModel | None:
        self.calls.append("account")
        return self.account

    async def acquire_snapshot_lock(self, **values: object) -> None:
        self.calls.append("snapshot_lock")
        self.snapshot_lock_values = values

    async def lock_canonical_evidence(self, account_id: str) -> None:
        self.calls.append("canonical_locks")

    async def lock_market_evidence_tables(self) -> None:
        self.calls.append("market_locks")

    async def lock_liability_evidence_table(self) -> None:
        self.calls.append("liability_lock")

    async def load_existing_snapshot(self, **values: object) -> AccountSnapshotModel | None:
        self.calls.append("existing")
        self.existing_values = values
        return self.existing

    async def load_snapshot_by_id(self, snapshot_id: str) -> AccountSnapshotModel | None:
        self.calls.append("id_conflict")
        return None

    async def load_snapshot_items(self, snapshot_id: str) -> tuple[AccountSnapshotItemModel, ...]:
        self.calls.append("existing_items")
        return self.existing_items

    def add_snapshot(self, snapshot: AccountSnapshotModel) -> None:
        self.calls.append("add_snapshot")
        self.inserted_snapshot = snapshot

    def add_items(self, items: tuple[AccountSnapshotItemModel, ...]) -> None:
        self.calls.append("add_items")
        self.inserted_items = items

    async def flush(self) -> None:
        self.calls.append("flush")
        self.flush_count += 1
        if self.flush_error is not None:
            raise self.flush_error

    async def reload_snapshot(self, snapshot_id: str) -> AccountSnapshotModel | None:
        self.calls.append("reload_snapshot")
        if self.reload_mismatch:
            assert self.inserted_snapshot is not None
            self.inserted_snapshot.cash_value = Decimal("999")
        return self.inserted_snapshot

    async def reload_snapshot_items(self, snapshot_id: str) -> tuple[AccountSnapshotItemModel, ...]:
        self.calls.append("reload_items")
        return self.inserted_items


def _account() -> AccountModel:
    return AccountModel(
        id="account-1",
        name="Broker",
        type=AccountType.broker,
        currency="CZK",
        color=None,
        is_archived=False,
        archived_at=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        notes=None,
    )


def _command(**changes: object) -> WriteAccountSnapshotCommand:
    values: dict[str, object] = {
        "account_id": "account-1",
        "snapshot_timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": CALCULATED_AT,
        "created_at": CREATED_AT,
        "is_recalculated": True,
    }
    values.update(changes)
    return WriteAccountSnapshotCommand(**cast(Any, values))


def _json(value: str) -> CanonicalJsonObject:
    return CanonicalJsonObject((("CZK", value),))


def _projection() -> ExpectedAccountSnapshotPersistence:
    snapshot = ExpectedAccountSnapshotRow(
        id="snapshot-1",
        account_id="account-1",
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        currency="CZK",
        cash_value=Decimal("100"),
        investment_value=Decimal("200"),
        investment_cost_basis=Decimal("150"),
        liabilities_value=Decimal(0),
        total_value=Decimal("300"),
        is_recalculated=True,
        calculated_at=CALCULATED_AT,
        calculation_version=1,
        created_at=CREATED_AT,
        net_deposits_value=Decimal("50"),
        realized_pnl_value=Decimal("10"),
        unrealized_pnl_value=Decimal("50"),
        fees_value=Decimal("2"),
        taxes_value=Decimal("1"),
        cash_value_by_currency=_json("100.000000"),
        investment_value_by_currency=_json("200.0000000000"),
        investment_cost_basis_by_currency=_json("150.0000000000"),
        net_deposits_by_currency=_json("50.000000"),
        realized_pnl_by_currency=_json("10.000000"),
        unrealized_pnl_by_currency=_json("50.000000"),
        fees_by_currency=_json("2.000000"),
        taxes_by_currency=_json("1.000000"),
        exchange_rates=CanonicalJsonObject(
            (("version", 1), ("snapshotRates", ()), ("historicalRateIds", ()))
        ),
    )
    item = ExpectedAccountSnapshotItemRow(
        id="item-1",
        snapshot_id=snapshot.id,
        asset_id="asset-1",
        listing_id="listing-1",
        symbol="VWCE",
        quantity=Decimal("2"),
        price_per_unit=Decimal("100"),
        price_currency="CZK",
        price_source=PriceSource.broker,
        price_timestamp=datetime(2026, 7, 27),
        value=Decimal("200"),
        cost_basis=Decimal("150"),
        cost_currency="CZK",
        allocation_pct=Decimal("100"),
        created_at=CREATED_AT,
        native_value=Decimal("200"),
        value_currency="CZK",
        native_cost_basis=Decimal("150"),
        native_cost_currency="CZK",
    )
    return ExpectedAccountSnapshotPersistence(
        snapshot=snapshot,
        items=(item,),
        audit=AccountSnapshotPersistenceAudit(
            selected_price_ids=("price-1",),
            selected_snapshot_exchange_rate_ids=(),
            selected_historical_exchange_rate_ids=(),
        ),
    )


def _liability_projection(
    amount: Decimal = Decimal("115.000000"),
) -> ExpectedAccountSnapshotPersistence:
    base = _projection()
    return ExpectedAccountSnapshotPersistence(
        snapshot=replace(
            base.snapshot,
            cash_value=Decimal(0),
            investment_value=Decimal(0),
            investment_cost_basis=Decimal(0),
            liabilities_value=amount,
            total_value=-amount,
            net_deposits_value=Decimal(0),
            realized_pnl_value=Decimal(0),
            unrealized_pnl_value=Decimal(0),
            fees_value=Decimal(0),
            taxes_value=Decimal(0),
            cash_value_by_currency=CanonicalJsonObject(()),
            investment_value_by_currency=CanonicalJsonObject(()),
            investment_cost_basis_by_currency=CanonicalJsonObject(()),
            net_deposits_by_currency=CanonicalJsonObject(()),
            realized_pnl_by_currency=CanonicalJsonObject(()),
            unrealized_pnl_by_currency=CanonicalJsonObject(()),
            fees_by_currency=CanonicalJsonObject(()),
            taxes_by_currency=CanonicalJsonObject(()),
        ),
        items=(),
        audit=AccountSnapshotPersistenceAudit(
            selected_price_ids=(),
            selected_snapshot_exchange_rate_ids=(),
            selected_historical_exchange_rate_ids=(),
            selected_liability_balance_id="liability-balance-1",
            selected_liability_effective_at=datetime(2026, 7, 27),
            selected_liability_source=LiabilityBalanceSource.statement,
        ),
    )


def _persisted(
    projection: ExpectedAccountSnapshotPersistence,
) -> tuple[AccountSnapshotModel, tuple[AccountSnapshotItemModel, ...]]:
    return (
        AccountSnapshotModel(**projection.snapshot.model_values()),
        tuple(AccountSnapshotItemModel(**item.model_values()) for item in projection.items),
    )


def _writer(
    *,
    projection: ExpectedAccountSnapshotPersistence | None = None,
) -> tuple[AccountSnapshotWriter, _Session, _Repository, _Evidence, list[object]]:
    plan = projection or _projection()
    session = _Session()
    repository = _Repository(plan)
    evidence = _Evidence()
    projection_calls: list[object] = []

    def build(evidence_value: object, metadata: object) -> ExpectedAccountSnapshotPersistence:
        projection_calls.extend((evidence_value, metadata))
        return plan

    writer = AccountSnapshotWriter(
        cast(Any, session),
        repository=cast(Any, repository),
        evidence_service=evidence,
        projection_builder=cast(Any, build),
    )
    return writer, session, repository, evidence, projection_calls


@pytest.mark.parametrize(
    "command",
    [
        _command(account_id=""),
        _command(snapshot_timestamp="2026-07-28"),
        _command(snapshot_timestamp=datetime(2026, 7, 28, tzinfo=UTC)),
        _command(snapshot_timestamp=datetime(2026, 7, 28, 0, 0, 0, 1)),
        _command(granularity="day"),
        _command(source="manual_recalculation"),
        _command(calculation_version=True),
        _command(calculation_version=0),
        _command(calculated_at=datetime(2026, 7, 28, 0, 0, 0, 1)),
        _command(created_at=datetime(2026, 7, 28, tzinfo=UTC)),
        _command(is_recalculated=cast(bool, 1)),
        _command(output_currency=""),
        _command(output_currency=" "),
        _command(output_currency="eur"),
        _command(output_currency=" EUR"),
        _command(output_currency="EUR "),
        _command(output_currency=cast(str, 1)),
    ],
)
@pytest.mark.asyncio
async def test_invalid_command_fails_before_transaction(command: object) -> None:
    writer, session, repository, evidence, projection_calls = _writer()
    with pytest.raises(AccountSnapshotWriteStateError):
        await writer.write(cast(Any, command))
    assert session.begin_count == 0
    assert repository.calls == []
    assert evidence.calls == []
    assert projection_calls == []


@pytest.mark.asyncio
async def test_created_composes_evidence_projection_and_persistence_once() -> None:
    writer, session, repository, evidence, projection_calls = _writer()
    result = await writer.write(_command())

    assert result == AccountSnapshotWriteResult(
        snapshot_id="snapshot-1",
        account_id="account-1",
        disposition=AccountSnapshotWriteDisposition.created,
        item_count=1,
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="CZK",
    )
    assert len(evidence.calls) == 1
    evidence_command = cast(BuildAccountSnapshotEvidenceCommand, evidence.calls[0])
    assert evidence_command.account_id == "account-1"
    assert evidence_command.snapshot_timestamp == SNAPSHOT_AT
    assert evidence_command.calculation_version == 1
    assert evidence_command.output_currency == "CZK"
    assert projection_calls[0] is evidence.value
    metadata = cast(AccountSnapshotPersistenceMetadata, projection_calls[1])
    assert metadata.calculated_at == CALCULATED_AT
    assert metadata.created_at == CREATED_AT
    assert metadata.is_recalculated is True
    assert repository.calls[:4] == [
        "account",
        "snapshot_lock",
        "canonical_locks",
        "market_locks",
    ]
    assert repository.flush_count == 2
    assert session.begin_count == 1
    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_exact_replay_inserts_nothing_and_returns_replayed() -> None:
    projection = _projection()
    writer, session, repository, _, _ = _writer(projection=projection)
    repository.existing, repository.existing_items = _persisted(projection)

    result = await writer.write(_command())

    assert result.disposition is AccountSnapshotWriteDisposition.replayed
    assert repository.inserted_snapshot is None
    assert repository.inserted_items == ()
    assert repository.flush_count == 0
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_liability_zero_item_create_and_replay_skip_investment_locks() -> None:
    projection = _liability_projection()
    writer, session, repository, _, _ = _writer(projection=projection)
    repository.account.type = AccountType.loan

    created = await writer.write(_command())

    assert created.disposition is AccountSnapshotWriteDisposition.created
    assert created.item_count == 0
    assert repository.inserted_items == ()
    assert repository.calls[:2] == ["account", "snapshot_lock"]
    assert repository.calls[:3] == ["account", "snapshot_lock", "liability_lock"]
    assert "canonical_locks" not in repository.calls
    assert "market_locks" not in repository.calls
    assert session.commit_count == 1

    replay_writer, replay_session, replay_repository, _, _ = _writer(projection=projection)
    replay_repository.account.type = AccountType.loan
    replay_repository.existing, replay_repository.existing_items = _persisted(projection)

    replayed = await replay_writer.write(_command())

    assert replayed.disposition is AccountSnapshotWriteDisposition.replayed
    assert replayed.item_count == 0
    assert replay_repository.inserted_snapshot is None
    assert replay_repository.flush_count == 0
    assert replay_session.commit_count == 1


@pytest.mark.asyncio
async def test_liability_snapshot_rejects_unexpected_existing_item() -> None:
    projection = _liability_projection()
    writer, session, repository, _, _ = _writer(projection=projection)
    repository.account.type = AccountType.credit_card
    repository.existing, _ = _persisted(projection)
    repository.existing_items = _persisted(_projection())[1]

    with pytest.raises(AccountSnapshotWriteConflictError):
        await writer.write(_command())

    assert repository.inserted_snapshot is None
    assert repository.flush_count == 0
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_changed_liability_amount_conflicts_without_repair() -> None:
    projection = _liability_projection()
    writer, session, repository, _, _ = _writer(projection=projection)
    repository.account.type = AccountType.mortgage
    persisted_snapshot, persisted_items = _persisted(projection)
    persisted_snapshot.liabilities_value = Decimal("114.000000")
    persisted_snapshot.total_value = Decimal("-114.000000")
    repository.existing = persisted_snapshot
    repository.existing_items = persisted_items

    with pytest.raises(AccountSnapshotWriteConflictError):
        await writer.write(_command())

    assert persisted_snapshot.liabilities_value == Decimal("114.000000")
    assert repository.flush_count == 0
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda snapshot, items: setattr(snapshot, "cash_value", Decimal("999")),
        lambda snapshot, items: setattr(
            snapshot, "exchange_rates", {"version": 2, "snapshotRates": []}
        ),
        lambda snapshot, items: setattr(snapshot, "created_at", datetime(2026, 7, 29)),
        lambda snapshot, items: setattr(snapshot, "id", "wrong-id"),
        lambda snapshot, items: items.clear(),
        lambda snapshot, items: items.append(
            AccountSnapshotItemModel(**_projection().items[0].model_values())
        ),
        lambda snapshot, items: setattr(items[0], "value", Decimal("999")),
        lambda snapshot, items: setattr(items[0], "id", "wrong-item-id"),
    ],
)
@pytest.mark.asyncio
async def test_existing_physical_difference_is_conflict(corrupt: Any) -> None:
    projection = _projection()
    writer, session, repository, _, _ = _writer(projection=projection)
    snapshot, persisted = _persisted(projection)
    items = list(persisted)
    corrupt(snapshot, items)
    repository.existing = snapshot
    repository.existing_items = tuple(items)

    with pytest.raises(AccountSnapshotWriteConflictError):
        await writer.write(_command())

    assert repository.inserted_snapshot is None
    assert repository.flush_count == 0
    assert session.rollback_count == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_flush_and_reload_failures_roll_back_outer_transaction() -> None:
    writer, session, repository, _, _ = _writer()
    repository.flush_error = RuntimeError("controlled")
    with pytest.raises(RuntimeError, match="controlled"):
        await writer.write(_command())
    assert session.rollback_count == 1
    assert session.commit_count == 0

    writer, session, repository, _, _ = _writer()
    repository.reload_mismatch = True
    with pytest.raises(AccountSnapshotWriteStateError):
        await writer.write(_command())
    assert session.rollback_count == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_invalid_existing_session_is_rejected_without_nested_transaction() -> None:
    writer, session, repository, _, _ = _writer()
    session.active = True
    with pytest.raises(AccountSnapshotWriteStateError):
        await writer.write(_command())
    assert session.begin_count == 0
    assert repository.calls == []


def test_command_result_and_projection_are_frozen() -> None:
    command = _command()
    result = AccountSnapshotWriteResult(
        snapshot_id="snapshot-1",
        account_id="account-1",
        disposition=AccountSnapshotWriteDisposition.created,
        item_count=1,
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="CZK",
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, command).account_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).item_count = 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "other-account"),
        ("timestamp", datetime(2026, 7, 29)),
        ("granularity", SnapshotGranularity.month),
        ("currency", "EUR"),
        ("source", SnapshotSource.scheduled),
        ("calculation_version", 2),
        ("calculated_at", datetime(2026, 7, 29)),
        ("created_at", datetime(2026, 7, 29)),
        ("is_recalculated", False),
    ],
)
@pytest.mark.asyncio
async def test_projection_identity_mismatch_fails_before_replay(
    field: str,
    value: object,
) -> None:
    projection = _projection()
    mismatched = replace(
        projection,
        snapshot=replace(cast(Any, projection.snapshot), **{field: value}),
    )
    writer, session, repository, _, _ = _writer(projection=mismatched)
    with pytest.raises(AccountSnapshotWriteStateError):
        await writer.write(_command())
    assert repository.inserted_snapshot is None
    assert "existing" not in repository.calls
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(None, "CZK"), ("CZK", "CZK"), ("EUR", "EUR")],
)
@pytest.mark.asyncio
async def test_output_currency_resolves_lock_evidence_replay_and_result(
    requested: str | None,
    expected: str,
) -> None:
    projection = _projection()
    if expected != projection.snapshot.currency:
        projection = replace(
            projection,
            snapshot=replace(projection.snapshot, currency=expected),
        )
    writer, _, repository, evidence, _ = _writer(projection=projection)

    result = await writer.write(_command(output_currency=requested))

    assert repository.snapshot_lock_values == {
        "account_id": "account-1",
        "timestamp": SNAPSHOT_AT,
        "currency": expected,
        "granularity": SnapshotGranularity.day,
    }
    assert repository.existing_values == repository.snapshot_lock_values
    evidence_command = cast(BuildAccountSnapshotEvidenceCommand, evidence.calls[0])
    assert evidence_command.output_currency == expected
    assert result.currency == expected


@pytest.mark.asyncio
async def test_mixed_currency_liability_lock_order_and_replay_identity() -> None:
    projection = _liability_projection()
    projection = replace(
        projection,
        snapshot=replace(projection.snapshot, currency="EUR"),
    )
    writer, _, repository, evidence, _ = _writer(projection=projection)
    repository.account.type = AccountType.loan

    await writer.write(_command(output_currency="EUR"))

    assert repository.calls[:5] == [
        "account",
        "snapshot_lock",
        "liability_lock",
        "market_locks",
        "existing",
    ]
    assert "canonical_locks" not in repository.calls
    assert cast(BuildAccountSnapshotEvidenceCommand, evidence.calls[0]).output_currency == "EUR"
    assert repository.existing_values is not None
    assert repository.existing_values["currency"] == "EUR"


def test_snapshot_lock_scope_includes_output_currency_and_milliseconds() -> None:
    timestamp = datetime(2026, 7, 28, 1, 2, 3, 456000)
    default_scope = account_snapshot_lock_scope(
        account_id="account-1",
        timestamp=timestamp,
        currency="CZK",
        granularity=SnapshotGranularity.minute,
    )
    repeated_scope = account_snapshot_lock_scope(
        account_id="account-1",
        timestamp=timestamp,
        currency="CZK",
        granularity=SnapshotGranularity.minute,
    )
    mixed_scope = account_snapshot_lock_scope(
        account_id="account-1",
        timestamp=timestamp,
        currency="EUR",
        granularity=SnapshotGranularity.minute,
    )

    assert default_scope == repeated_scope
    assert default_scope != mixed_scope
    assert default_scope == "\0".join(
        (
            "snapshots:account",
            "account-1",
            "2026-07-28T01:02:03.456",
            "CZK",
            "minute",
        )
    )


class _ExecuteSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


@pytest.mark.asyncio
async def test_liability_lock_emits_one_fixed_share_table_statement() -> None:
    session = _ExecuteSession()
    repository = AccountSnapshotWriterRepository(cast(Any, session))

    await repository.lock_liability_evidence_table()

    assert session.statements == ['LOCK TABLE public."LiabilityBalance" IN SHARE MODE']
