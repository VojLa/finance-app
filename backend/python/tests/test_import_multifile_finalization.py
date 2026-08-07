from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import (
    ImportSource,
    ImportStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import HoldingRebuildUnavailableError
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    ImportBatchFinalizationStateError,
    ImportMultiFileFinalizationService,
)
from app.modules.imports.posting_service import PostImportBatchResult
from app.modules.imports.service import ImportBatchNotFoundError
from app.modules.market_data.models import MarketEvidenceRefreshResult
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshResult,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode

FIRST_COMPLETED_AT = datetime(2036, 8, 3, 10, 1, 1, 123000)
FINAL_COMPLETED_AT = datetime(2036, 8, 3, 10, 4, 59, 999000)
FINAL_BUCKET = datetime(2036, 8, 3, 10, 4)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True

    async def __aexit__(self, *_: object) -> None:
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _rollback(self) -> None:
        self.active = False

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _BatchRepository:
    def __init__(self, batches: Mapping[str, object]) -> None:
        self.batches = batches

    async def get_for_account(self, *, account_id: str, batch_id: str) -> object | None:
        batch = self.batches.get(batch_id)
        return batch if batch is not None and cast(Any, batch).account_id == account_id else None


class _AuditRepository:
    async def acquire_audit_lock(self, _: str) -> None:
        pass

    async def load_log_for_update(self, _: str) -> None:
        return None

    def add_log(self, _: object) -> None:
        pass

    async def flush(self) -> None:
        pass


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


def _command(*batch_ids: str) -> FinalizeImportBatchesCommand:
    return FinalizeImportBatchesCommand(
        principal=_principal(),
        account_id="account-a",
        batch_ids=tuple(batch_ids) or ("batch-a", "batch-b", "batch-c"),
    )


def _posting(
    batch_id: str,
    *,
    completed_at: datetime,
    imported: int = 1,
    investments: int = 1,
) -> PostImportBatchResult:
    return PostImportBatchResult(
        batch_id=batch_id,
        status=ImportStatus.completed,
        rows_total=imported,
        rows_imported=imported,
        rows_skipped=0,
        completed_at=completed_at,
        replayed=True,
        transaction_rows_imported=imported - investments,
        investment_event_rows_imported=investments,
    )


def _combined_result() -> ExecuteMarketBackedSnapshotRefreshResult:
    execution = ExecutedAccountSnapshotRefresh(
        account_id="account-a",
        snapshot_id="snapshot-a",
        mode=AccountSnapshotRefreshMode.refresh,
        disposition=AccountSnapshotRefreshExecutionDisposition.created,
    )
    snapshots = ExecuteUserSnapshotRefreshResult(
        user_id="user-a",
        snapshot_timestamp=FINAL_BUCKET,
        granularity=SnapshotGranularity.minute,
        output_currency="CZK",
        source=SnapshotSource.import_event,
        calculation_version=1,
        account_snapshots=(execution,),
        required_account_snapshot_identities=(
            SelectedAccountSnapshotIdentity("account-a", "snapshot-a"),
        ),
        net_worth_snapshot_id="net-worth-a",
        net_worth_disposition=NetWorthSnapshotWriteDisposition.created,
        refresh_account_count=1,
        reuse_only_account_count=0,
        created_account_snapshot_count=1,
        replayed_account_snapshot_count=0,
        reused_account_snapshot_count=0,
        selected_account_snapshot_count=1,
    )
    market = MarketEvidenceRefreshResult(
        user_id="user-a",
        snapshot_timestamp=FINAL_BUCKET,
        output_currency="CZK",
        required_price_count=0,
        required_fx_count=0,
        price_ids=(),
        exchange_rate_ids=(),
        prices_created=0,
        prices_replayed=0,
        rates_created=0,
        rates_replayed=0,
    )
    return ExecuteMarketBackedSnapshotRefreshResult(market=market, snapshots=snapshots)


def _service(
    *,
    batches: Mapping[str, object] | None = None,
    postings: tuple[PostImportBatchResult, ...] | None = None,
) -> tuple[ImportMultiFileFinalizationService, Mock, Mock, Mock]:
    session = _Session()
    persisted = batches or {
        batch_id: SimpleNamespace(
            id=batch_id,
            account_id="account-a",
            user_id="user-a",
            source=ImportSource.trading212,
            status=ImportStatus.completed,
            completed_at=completed_at,
        )
        for batch_id, completed_at in (
            ("batch-a", FIRST_COMPLETED_AT),
            ("batch-b", datetime(2036, 8, 3, 10, 2)),
            ("batch-c", FINAL_COMPLETED_AT),
        )
    }
    results = iter(
        postings
        or (
            _posting("batch-a", completed_at=FIRST_COMPLETED_AT),
            _posting("batch-b", completed_at=datetime(2036, 8, 3, 10, 2)),
            _posting("batch-c", completed_at=FINAL_COMPLETED_AT),
        )
    )
    posting = Mock(post_batch=AsyncMock(side_effect=lambda _: next(results)))
    posting_factory = Mock(return_value=posting)
    holding = Mock(
        rebuild=AsyncMock(
            return_value=HoldingRebuildResponse(
                account_id="account-a",
                created=1,
                updated=0,
                deleted=0,
                total=1,
                replayed=False,
                rebuilt_at=FINAL_COMPLETED_AT,
            )
        )
    )
    holding_factory = Mock(return_value=holding)
    market = Mock(execute=AsyncMock(return_value=_combined_result()))
    service = ImportMultiFileFinalizationService(
        cast(AsyncSession, session),
        market_backed_service=market,
        posting_service_factory=posting_factory,
        holding_service_factory=holding_factory,
        repository_factory=Mock(return_value=_AuditRepository()),
        batch_repository_factory=Mock(return_value=_BatchRepository(persisted)),
    )
    return service, posting_factory, holding_factory, market


@pytest.fixture(autouse=True)
def _authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.imports.multi_file_service.require_account_access",
        AsyncMock(),
    )


async def test_three_batches_have_one_holdings_and_market_finalization() -> None:
    service, posting_factory, holding_factory, market = _service()

    result = await service.finalize(_command())

    assert result.batch_ids == ("batch-a", "batch-b", "batch-c")
    assert result.snapshot_refresh_status.value == "created"
    assert posting_factory.call_count == 3
    holding_factory.assert_called_once()
    assert holding_factory.call_args.args[1]() == FINAL_COMPLETED_AT
    market.execute.assert_awaited_once_with(
        ExecuteMarketBackedSnapshotRefreshCommand(
            user_id="user-a",
            snapshot_timestamp=FINAL_BUCKET,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.import_event,
            calculation_version=1,
            calculated_at=FINAL_BUCKET,
            created_at=FINAL_BUCKET,
            is_recalculated=False,
        )
    )


async def test_zero_import_skips_holdings_and_market() -> None:
    postings = tuple(
        _posting(
            batch_id,
            completed_at=completed_at,
            imported=0,
            investments=0,
        )
        for batch_id, completed_at in (
            ("batch-a", FIRST_COMPLETED_AT),
            ("batch-b", datetime(2036, 8, 3, 10, 2)),
            ("batch-c", FINAL_COMPLETED_AT),
        )
    )
    service, posting_factory, holding_factory, market = _service(postings=postings)

    result = await service.finalize(_command())

    assert result.snapshot_refresh_status.value == "not_required"
    assert posting_factory.call_count == 3
    holding_factory.assert_not_called()
    market.execute.assert_not_awaited()


async def test_cash_only_batches_skip_holdings_but_refresh_once() -> None:
    postings = tuple(
        _posting(batch_id, completed_at=completed_at, investments=0)
        for batch_id, completed_at in (
            ("batch-a", FIRST_COMPLETED_AT),
            ("batch-b", datetime(2036, 8, 3, 10, 2)),
            ("batch-c", FINAL_COMPLETED_AT),
        )
    )
    service, _, holding_factory, market = _service(postings=postings)

    await service.finalize(_command())

    holding_factory.assert_not_called()
    market.execute.assert_awaited_once()


async def test_market_failure_returns_unavailable_and_retry_can_complete() -> None:
    failed_service, _, failed_holding_factory, failed_market = _service()
    failed_market.execute.side_effect = MarketBackedSnapshotRefreshUnavailableError()

    failed = await failed_service.finalize(_command())

    assert failed.snapshot_refresh_status.value == "unavailable"
    failed_holding_factory.assert_called_once()
    failed_market.execute.assert_awaited_once()

    retry_service, _, retry_holding_factory, retry_market = _service()
    recovered = await retry_service.finalize(_command())

    assert recovered.snapshot_refresh_status.value == "created"
    retry_holding_factory.assert_called_once()
    retry_market.execute.assert_awaited_once()


async def test_holding_failure_remains_recoverable_with_the_same_batch_set() -> None:
    failed_service, _, failed_holding_factory, failed_market = _service()
    failed_holding_factory.return_value.rebuild.side_effect = HoldingRebuildUnavailableError()

    failed = await failed_service.finalize(_command())

    assert failed.snapshot_refresh_status.value == "unavailable"
    failed_holding_factory.assert_called_once()
    failed_market.execute.assert_not_awaited()

    retry_service, _, retry_holding_factory, retry_market = _service()
    recovered = await retry_service.finalize(_command())

    assert recovered.snapshot_refresh_status.value == "created"
    retry_holding_factory.assert_called_once()
    retry_market.execute.assert_awaited_once()


async def test_snapshot_conflict_remains_recoverable_with_the_same_batch_set() -> None:
    failed_service, _, failed_holding_factory, failed_market = _service()
    failed_market.execute.side_effect = MarketBackedSnapshotRefreshConflictError()

    failed = await failed_service.finalize(_command())

    assert failed.snapshot_refresh_status.value == "conflict"
    failed_holding_factory.assert_called_once()
    failed_market.execute.assert_awaited_once()

    retry_service, _, retry_holding_factory, retry_market = _service()
    recovered = await retry_service.finalize(_command())

    assert recovered.snapshot_refresh_status.value == "created"
    retry_holding_factory.assert_called_once()
    retry_market.execute.assert_awaited_once()


async def test_mixed_source_fails_before_posting() -> None:
    batches = {
        "batch-a": SimpleNamespace(
            account_id="account-a",
            user_id="user-a",
            source=ImportSource.trading212,
            status=ImportStatus.completed,
            completed_at=FIRST_COMPLETED_AT,
        ),
        "batch-b": SimpleNamespace(
            account_id="account-a",
            user_id="user-a",
            source=ImportSource.anycoin,
            status=ImportStatus.completed,
            completed_at=FINAL_COMPLETED_AT,
        ),
    }
    service, posting_factory, holding_factory, market = _service(batches=batches)

    with pytest.raises(ImportBatchFinalizationStateError):
        await service.finalize(_command("batch-a", "batch-b"))

    posting_factory.assert_not_called()
    holding_factory.assert_not_called()
    market.execute.assert_not_awaited()


async def test_foreign_principal_batch_is_nondisclosed() -> None:
    batches = {
        "batch-a": SimpleNamespace(
            account_id="account-a",
            user_id="other-user",
            source=ImportSource.trading212,
            status=ImportStatus.completed,
            completed_at=FIRST_COMPLETED_AT,
        )
    }
    service, posting_factory, _, market = _service(batches=batches)

    with pytest.raises(ImportBatchNotFoundError):
        await service.finalize(_command("batch-a"))

    posting_factory.assert_not_called()
    market.execute.assert_not_awaited()


async def test_posting_replay_transaction_leak_is_rolled_back() -> None:
    service, posting_factory, holding_factory, market = _service()
    session = cast(_Session, service.session)

    async def leaking_post(_: object) -> object:
        session.active = True
        raise RuntimeError("dependency detail")

    posting_factory.return_value = Mock(
        post_batch=AsyncMock(side_effect=leaking_post),
    )

    with pytest.raises(RuntimeError, match="active transaction"):
        await service.finalize(_command())

    session.rollback.assert_awaited_once()
    assert session.active is False
    holding_factory.assert_not_called()
    market.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "command",
    [
        object(),
        FinalizeImportBatchesCommand(_principal(), "account-a", ()),
        FinalizeImportBatchesCommand(_principal(), "account-a", ("batch-a", "batch-a")),
        FinalizeImportBatchesCommand(_principal(), "account-a", ("batch-b", "batch-a")),
        FinalizeImportBatchesCommand(_principal(), " account-a", ("batch-a",)),
    ],
)
async def test_invalid_command_fails_before_database(command: object) -> None:
    service, posting_factory, _, market = _service()

    with pytest.raises(RuntimeError):
        await service.finalize(cast(Any, command))

    posting_factory.assert_not_called()
    market.execute.assert_not_awaited()


def test_command_and_result_are_immutable() -> None:
    command = _command()
    with pytest.raises(FrozenInstanceError):
        command.account_id = "other"  # type: ignore[misc]
