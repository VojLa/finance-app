"""Immutable internal contracts for strict daily-baseline current value."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.daily_baselines.service import DailySnapshotBaseline
from app.modules.market_data.models import MarketEvidenceRefreshPlan
from app.modules.portfolio_snapshot.aggregate_models import (
    AccountPortfolioPresentationView,
    MultiAccountPortfolioView,
)


@dataclass(frozen=True, slots=True)
class CurrentValuePlan:
    """Stable server-derived lineage and exact provider requirements."""

    as_of: datetime
    baseline: DailySnapshotBaseline
    market_plan: MarketEvidenceRefreshPlan
    frozen_account_ids: tuple[str, ...]
    listing_selections: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CurrentPortfolioResult:
    """Ephemeral current portfolio plus its persisted daily lineage."""

    as_of: datetime
    baseline_id: str
    baseline_timestamp: datetime
    baseline_net_worth_snapshot_id: str
    portfolio: MultiAccountPortfolioView
    account_presentations: tuple[AccountPortfolioPresentationView, ...]
