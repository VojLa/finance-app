from datetime import datetime

from app.db.models.enums import AccountType, SnapshotSource
from app.modules.daily_baselines.service import (
    DailyBaselineAccount,
    DailyBaselineChange,
    DailySnapshotBaseline,
    freeze_baseline_post_changes,
)


def test_publication_freeze_removes_only_the_active_account_delta() -> None:
    baseline = DailySnapshotBaseline(
        baseline_id="baseline",
        user_id="reader",
        net_worth_snapshot_id="net-worth",
        timestamp=datetime(2040, 1, 1),
        currency="EUR",
        calculation_version=1,
        source=SnapshotSource.manual_recalculation,
        accounts=(
            DailyBaselineAccount(
                account_id="active-account",
                account_type=AccountType.bank,
                account_currency="EUR",
                primary_snapshot_id="active-primary",
                presentation_snapshot_id="active-presentation",
                canonical_revision=1,
                investment_revision=None,
                holding_revision=None,
                selected_liability_balance_id=None,
            ),
            DailyBaselineAccount(
                account_id="other-account",
                account_type=AccountType.bank,
                account_currency="EUR",
                primary_snapshot_id="other-primary",
                presentation_snapshot_id="other-presentation",
                canonical_revision=1,
                investment_revision=None,
                holding_revision=None,
                selected_liability_balance_id=None,
            ),
        ),
        post_baseline_changes=(
            DailyBaselineChange(
                account_id="active-account",
                revision=2,
                kind="transaction",
                entity_id="active-change",
                financial_timestamp=datetime(2040, 1, 2),
            ),
            DailyBaselineChange(
                account_id="other-account",
                revision=2,
                kind="transaction",
                entity_id="other-change",
                financial_timestamp=datetime(2040, 1, 2),
            ),
        ),
    )

    frozen = freeze_baseline_post_changes(
        baseline,
        account_ids=("active-account",),
    )

    assert frozen is not baseline
    assert frozen.post_baseline_changes == (baseline.post_baseline_changes[1],)
    assert baseline.post_baseline_changes[0].account_id == "active-account"
