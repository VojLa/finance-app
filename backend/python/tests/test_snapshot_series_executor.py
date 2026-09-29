from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.snapshot_refresh.series_executor import (
    ExecuteSnapshotSeriesCommand,
    SnapshotSeriesAccountEvidence,
    SnapshotSeriesAccountManifestEntry,
    SnapshotSeriesAccountSelection,
    SnapshotSeriesExecutionStateError,
    SnapshotSeriesExecutor,
    SnapshotSeriesPoint,
    SnapshotSeriesPublicationManifest,
    SnapshotSeriesTarget,
    StagedAccountSnapshot,
    StagedUserSnapshotSeriesProjection,
    StageUserSnapshotSeriesProjectionCommand,
    generation_id_for_job,
)
from app.modules.snapshots.account_projection import (
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)
from app.modules.snapshots.persistence_projection import ExpectedAccountSnapshotPersistence

AT = datetime(2034, 5, 1)
CALCULATED_AT = AT + timedelta(seconds=1)
CREATED_AT = AT + timedelta(seconds=2)


def _evidence(
    *,
    account_id: str,
    currency: str,
    timestamp: datetime = AT,
) -> CompleteAccountSnapshotEvidence:
    amount = CurrencyAmount(currency=currency, amount=Decimal(0))
    zero = ExactSnapshotMetric(value=Decimal(0), breakdown=(amount,))
    return CompleteAccountSnapshotEvidence(
        valuation=ExpectedAccountSnapshotValuation(
            account_id=account_id,
            timestamp=timestamp,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            currency=currency,
            calculation_version=1,
            cash_value=Decimal(0),
            investment_value=Decimal(0),
            investment_cost_basis=Decimal(0),
            liabilities_value=Decimal(0),
            total_value=Decimal(0),
            cash_value_by_currency=(amount,),
            investment_value_by_currency=(amount,),
            investment_cost_basis_by_currency=(amount,),
            liabilities_value_by_currency=(),
            exchange_rates=(),
            items=(),
        ),
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=zero,
        fees=zero,
        taxes=zero,
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(),
        selected_historical_exchange_rate_ids=(),
    )


def _command(
    *,
    account_evidence: tuple[SnapshotSeriesAccountEvidence, ...] | None = None,
) -> ExecuteSnapshotSeriesCommand:
    evidence = account_evidence or (
        SnapshotSeriesAccountEvidence(
            account_id="account-shared",
            account_currency="USD",
            evidence=_evidence(account_id="account-shared", currency="EUR"),
            canonical_revision=1,
            investment_revision=1,
            holding_revision=1,
        ),
        SnapshotSeriesAccountEvidence(
            account_id="account-shared",
            account_currency="USD",
            evidence=_evidence(account_id="account-shared", currency="USD"),
            canonical_revision=1,
            investment_revision=1,
            holding_revision=1,
        ),
    )
    return ExecuteSnapshotSeriesCommand(
        job_id="durable-job-1",
        targets=(
            SnapshotSeriesTarget(
                user_id="user-eur",
                output_currency="EUR",
                account_ids=("account-shared",),
            ),
            SnapshotSeriesTarget(
                user_id="user-usd",
                output_currency="USD",
                account_ids=("account-shared",),
            ),
        ),
        points=(
            SnapshotSeriesPoint(
                timestamp=AT,
                granularity=SnapshotGranularity.day,
                source=SnapshotSource.manual_recalculation,
                calculation_version=1,
                calculated_at=CALCULATED_AT,
                created_at=CREATED_AT,
                is_recalculated=True,
                account_evidence=evidence,
            ),
        ),
    )


class _AccountStager:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.projections: list[ExpectedAccountSnapshotPersistence] = []

    async def stage(
        self,
        entry: SnapshotSeriesAccountManifestEntry,
    ) -> StagedAccountSnapshot:
        projection = entry.projection
        self.calls.append(f"account:{projection.snapshot.currency}")
        self.projections.append(projection)
        snapshot = projection.snapshot
        return StagedAccountSnapshot(
            snapshot_id=snapshot.id,
            account_id=snapshot.account_id,
            timestamp=snapshot.timestamp,
            granularity=snapshot.granularity,
            currency=snapshot.currency,
            generation_id=snapshot.generation_id,
        )


class _UserStager:
    def __init__(self, calls: list[str], *, fail_for_user: str | None = None) -> None:
        self.calls = calls
        self.fail_for_user = fail_for_user
        self.commands: list[StageUserSnapshotSeriesProjectionCommand] = []

    async def stage(
        self,
        command: StageUserSnapshotSeriesProjectionCommand,
    ) -> StagedUserSnapshotSeriesProjection:
        self.calls.append(f"user:{command.user_id}")
        self.commands.append(command)
        if command.user_id == self.fail_for_user:
            raise RuntimeError("staging failed")
        return StagedUserSnapshotSeriesProjection(
            generation_id=command.generation_id,
            user_id=command.user_id,
            timestamp=command.timestamp,
            granularity=command.granularity,
            source=command.source,
            calculation_version=command.calculation_version,
            calculated_at=command.calculated_at,
            created_at=command.created_at,
            is_recalculated=command.is_recalculated,
            output_currency=command.output_currency,
            output_account_snapshots=command.output_account_snapshots,
            native_account_snapshots=command.native_account_snapshots,
            portfolio_snapshot_id=f"portfolio:{command.user_id}",
            net_worth_snapshot_id=f"net-worth:{command.user_id}",
            baseline_id=f"baseline:{command.user_id}",
        )


class _Publisher:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.manifests: list[SnapshotSeriesPublicationManifest] = []

    async def publish(self, manifest: SnapshotSeriesPublicationManifest) -> None:
        self.calls.append("publish")
        self.manifests.append(manifest)

    async def retire_user(self, _user_id: str, *, job_created_at: datetime) -> None:
        del job_created_at
        raise AssertionError("retirement is not expected")


@pytest.mark.asyncio
async def test_stages_shared_native_once_and_publishes_complete_deterministic_manifest() -> None:
    calls: list[str] = []
    account_stager = _AccountStager(calls)
    user_stager = _UserStager(calls)
    publisher = _Publisher(calls)
    executor = SnapshotSeriesExecutor(
        account_stager=account_stager,
        user_projection_stager=user_stager,
        publisher=publisher,
    )

    result = await executor.execute(_command())

    assert result.generation_id == generation_id_for_job("durable-job-1")
    assert calls == [
        "account:EUR",
        "account:USD",
        "user:user-eur",
        "user:user-usd",
        "publish",
    ]
    assert len(account_stager.projections) == 2
    assert {item.snapshot.currency for item in account_stager.projections} == {"EUR", "USD"}
    assert len(publisher.manifests) == 1
    manifest = publisher.manifests[0]
    assert manifest.generation_id == result.generation_id
    assert tuple(item.projection.snapshot.id for item in manifest.account_snapshots) == tuple(
        item.snapshot_id for item in result.account_snapshots
    )
    assert tuple(item.user_id for item in manifest.user_projections) == ("user-eur", "user-usd")
    assert user_stager.commands[0].output_account_snapshots == (
        SelectedAccountSnapshotIdentity(
            account_id="account-shared",
            snapshot_id=account_stager.projections[0].snapshot.id,
        ),
    )
    assert user_stager.commands[0].native_account_snapshots == (
        SnapshotSeriesAccountSelection(
            account_id="account-shared",
            snapshot_id=account_stager.projections[1].snapshot.id,
            currency="USD",
        ),
    )

    repeat_account_stager = _AccountStager([])
    repeat = await SnapshotSeriesExecutor(
        account_stager=repeat_account_stager,
        user_projection_stager=_UserStager([]),
        publisher=_Publisher([]),
    ).execute(_command())
    assert tuple(item.snapshot_id for item in repeat.account_snapshots) == tuple(
        item.snapshot_id for item in result.account_snapshots
    )


@pytest.mark.asyncio
async def test_rejects_missing_required_output_or_native_coordinate_before_staging() -> None:
    calls: list[str] = []
    publisher = _Publisher(calls)
    executor = SnapshotSeriesExecutor(
        account_stager=_AccountStager(calls),
        user_projection_stager=_UserStager(calls),
        publisher=publisher,
    )
    command = _command(
        account_evidence=(
            SnapshotSeriesAccountEvidence(
                account_id="account-shared",
                account_currency="USD",
                evidence=_evidence(account_id="account-shared", currency="EUR"),
                canonical_revision=1,
                investment_revision=1,
                holding_revision=1,
            ),
        )
    )

    with pytest.raises(SnapshotSeriesExecutionStateError):
        await executor.execute(command)

    assert calls == []
    assert publisher.manifests == []


@pytest.mark.asyncio
async def test_does_not_publish_when_any_user_point_is_not_completely_staged() -> None:
    calls: list[str] = []
    publisher = _Publisher(calls)
    executor = SnapshotSeriesExecutor(
        account_stager=_AccountStager(calls),
        user_projection_stager=_UserStager(calls, fail_for_user="user-usd"),
        publisher=publisher,
    )

    with pytest.raises(SnapshotSeriesExecutionStateError):
        await executor.execute(_command())

    assert calls == [
        "account:EUR",
        "account:USD",
        "user:user-eur",
        "user:user-usd",
    ]
    assert publisher.manifests == []
