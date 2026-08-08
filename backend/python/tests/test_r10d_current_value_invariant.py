"""Checkout-portable evidence for the R10-D current-value contract audit."""

from __future__ import annotations

import importlib
import inspect
from datetime import datetime
from typing import Any, cast

import pytest

from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.modules.liabilities.evidence_service import LiabilityBalanceEvidenceService
from app.modules.portfolio_history.repository import PortfolioHistoryRepository
from app.modules.snapshot_refresh.manual_service import (
    MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY,
    ManualUserSnapshotRefreshService,
    RecalculateUserSnapshotRefreshCommand,
    canonical_manual_user_snapshot_refresh_bucket,
)
from app.modules.snapshots.evidence_repository import AccountSnapshotEvidenceRepository

manual_support: Any = importlib.import_module("tests.test_snapshot_refresh_manual_service")


@pytest.mark.asyncio
async def test_manual_current_refresh_uses_clock_minute_and_projects_exact_manifest() -> None:
    service, _, market_backed, _ = manual_support._service()

    result = await cast(ManualUserSnapshotRefreshService, service).recalculate(
        RecalculateUserSnapshotRefreshCommand(principal=manual_support._principal())
    )

    assert MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY.value == "minute"
    assert canonical_manual_user_snapshot_refresh_bucket(manual_support.RAW_NOW) == (
        manual_support.BUCKET
    )
    command = market_backed.execute.await_args.args[0]
    assert command.snapshot_timestamp == manual_support.BUCKET
    assert command.granularity is MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY
    assert tuple((item.account_id, item.snapshot_id) for item in result.accounts) == (
        ("account-a", "snapshot-account-a"),
        ("account-b", "snapshot-account-b"),
        ("account-c", "snapshot-account-c"),
    )


def test_minute_bucket_is_not_a_daily_baseline_selector() -> None:
    value = datetime(2038, 5, 6, 21, 43, 59, 999999)

    assert canonical_manual_user_snapshot_refresh_bucket(value) == datetime(2038, 5, 6, 21, 43)


def test_physical_snapshots_have_no_canonical_event_watermark_or_persisted_manifest() -> None:
    account_columns = set(AccountSnapshotModel.__table__.columns.keys())
    item_columns = set(AccountSnapshotItemModel.__table__.columns.keys())
    net_worth_columns = set(NetWorthSnapshotModel.__table__.columns.keys())

    forbidden_cursor_fields = {
        "eventWatermark",
        "transactionWatermark",
        "movementWatermark",
        "canonicalCutoff",
        "includedEventIds",
    }
    assert forbidden_cursor_fields.isdisjoint(account_columns)
    assert forbidden_cursor_fields.isdisjoint(item_columns)
    assert {
        "selectedAccountSnapshotIds",
        "selectedAccountIds",
        "accountSnapshotManifest",
    }.isdisjoint(net_worth_columns)


def test_snapshot_evidence_reloads_complete_state_through_current_bucket() -> None:
    repository_source = inspect.getsource(AccountSnapshotEvidenceRepository)

    assert "TransactionModel.date <= through" in repository_source
    assert repository_source.count("InvestmentEventModel.date <= through") == 2
    assert "TransactionModel.date >" not in repository_source
    assert "InvestmentEventModel.date >" not in repository_source
    assert "baseline" not in repository_source.lower()
    assert "select(HoldingModel" in repository_source


def test_liability_persistence_is_point_in_time_evidence_not_an_event_delta() -> None:
    columns = set(LiabilityBalanceModel.__table__.columns.keys())
    source = inspect.getsource(LiabilityBalanceEvidenceService.select)

    assert {
        "effectiveAt",
        "outstandingPrincipal",
        "accruedInterest",
        "feesOutstanding",
        "totalOutstanding",
    } <= columns
    assert {"deltaAmount", "eventId", "previousBalanceId"}.isdisjoint(columns)
    assert "latest_at = max" in source
    assert "len(latest) != 1" in source


def test_history_remains_a_separate_persisted_net_worth_read() -> None:
    source = inspect.getsource(PortfolioHistoryRepository)

    assert "NetWorthSnapshotModel" in source
    assert "TransactionModel" not in source
    assert "InvestmentEventModel" not in source
    assert "HoldingModel" not in source
    assert "PriceSnapshotModel" not in source
    assert "ExchangeRateModel" not in source


def test_active_current_service_contains_no_daily_delta_implementation() -> None:
    source = inspect.getsource(ManualUserSnapshotRefreshService.recalculate)

    assert "market_backed_service.execute" in source
    assert "SnapshotGranularity.day" not in source
    assert "TransactionModel" not in source
    assert "InvestmentEventModel" not in source
    assert "NetWorthSnapshotModel" not in source
    assert "latest" not in source.lower()
