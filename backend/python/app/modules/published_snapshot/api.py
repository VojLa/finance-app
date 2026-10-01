"""Read the latest published snapshot set without live market acquisition."""

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic, perf_counter
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.db.models.enums import AccountType
from app.db.models.enums import SnapshotGranularity as DbSnapshotGranularity
from app.modules.current_value.api_models import (
    CurrentDashboardAccountResponse,
    CurrentDashboardResponse,
    CurrentPortfolioAccountResponse,
    CurrentPortfolioResponse,
)
from app.modules.daily_baselines.service import DailySnapshotBaseline, DailySnapshotBaselineService
from app.modules.dashboard_snapshot.api_models import (
    DashboardAssetTypeAllocationResponse,
    DashboardSnapshotSummaryResponse,
    DashboardTopPositionResponse,
)
from app.modules.dashboard_snapshot.projection import build_dashboard_snapshot_view
from app.modules.portfolio_snapshot.aggregation import portfolio_allocation_percentage
from app.modules.portfolio_snapshot.api_models import (
    PortfolioSnapshotAccountResponse,
    PortfolioSnapshotPositionResponse,
    PortfolioSnapshotSummaryResponse,
)
from app.modules.portfolio_snapshot.models import SnapshotGranularity
from app.modules.portfolio_snapshot.multi_account_api_models import (
    MultiAccountPortfolioAggregatePositionResponse,
    MultiAccountPortfolioSummaryResponse,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ReadAuthorizedMultiAccountPortfolioSnapshotResult,
)

router = APIRouter(tags=["published-snapshot"])
logger = structlog.get_logger(__name__)

_INVESTMENT_TYPES = frozenset((AccountType.broker, AccountType.exchange, AccountType.crypto_wallet))
_GRANULARITIES = {
    DbSnapshotGranularity.minute: SnapshotGranularity.minute,
    DbSnapshotGranularity.hour: SnapshotGranularity.hour,
    DbSnapshotGranularity.day: SnapshotGranularity.day,
    DbSnapshotGranularity.week: SnapshotGranularity.week,
    DbSnapshotGranularity.month: SnapshotGranularity.month,
}
_READ_CACHE_TTL_SECONDS = 10.0
_READ_CACHE_MAX_ENTRIES = 256
_STALE_AFTER = timedelta(minutes=30)
_read_cache: OrderedDict[
    tuple[str, str, tuple[str, ...] | None],
    tuple[float, ReadAuthorizedMultiAccountPortfolioSnapshotResult],
] = OrderedDict()


def _purge_expired(now: float) -> None:
    for key, (expires_at, _) in tuple(_read_cache.items()):
        if now >= expires_at:
            _read_cache.pop(key, None)


def _cache_key(
    *,
    user_id: str,
    baseline_id: str,
    account_types: frozenset[AccountType] | None,
) -> tuple[str, str, tuple[str, ...] | None]:
    return (
        user_id,
        baseline_id,
        None if account_types is None else tuple(sorted(item.value for item in account_types)),
    )


def _cached_result(
    key: tuple[str, str, tuple[str, ...] | None],
) -> ReadAuthorizedMultiAccountPortfolioSnapshotResult | None:
    now = monotonic()
    _purge_expired(now)
    cached = _read_cache.get(key)
    if cached is None:
        return None
    _, result = cached
    _read_cache.move_to_end(key)
    return result


def _cache_result(
    key: tuple[str, str, tuple[str, ...] | None],
    result: ReadAuthorizedMultiAccountPortfolioSnapshotResult,
) -> None:
    now = monotonic()
    _purge_expired(now)
    _read_cache[key] = (now + _READ_CACHE_TTL_SECONDS, result)
    _read_cache.move_to_end(key)
    while len(_read_cache) > _READ_CACHE_MAX_ENTRIES:
        _read_cache.popitem(last=False)


async def _read_latest(
    *,
    principal: CurrentPrincipal,
    session: AsyncSession,
    account_types: frozenset[AccountType] | None = None,
) -> tuple[DailySnapshotBaseline, ReadAuthorizedMultiAccountPortfolioSnapshotResult]:
    baseline_started_at = perf_counter()
    baseline = await DailySnapshotBaselineService(
        session
    ).select_published_manifest_for_authorized_read(user_id=principal.user_id)
    baseline_duration_ms = round((perf_counter() - baseline_started_at) * 1000, 2)
    cache_key = _cache_key(
        user_id=principal.user_id,
        baseline_id=baseline.baseline_id,
        account_types=account_types,
    )
    cached = _cached_result(cache_key)
    if cached is not None:
        logger.info(
            "financial_read_phase",
            phase="published_snapshot",
            cache_hit=True,
            manifest_read_ms=baseline_duration_ms,
            projection_read_ms=0.0,
        )
        return baseline, cached
    accounts = tuple(
        ExactAccountSnapshotSelection(
            account_id=account.account_id,
            required_snapshot_id=account.primary_snapshot_id,
        )
        for account in baseline.accounts
        if account_types is None or account.account_type in account_types
    )
    if not accounts:
        # The exact reader requires a non-empty coherent selector. A user without
        # investment accounts therefore has no portfolio snapshot to display.
        from app.modules.portfolio_snapshot.authorized_reader import portfolio_snapshot_unavailable

        raise portfolio_snapshot_unavailable()
    projection_started_at = perf_counter()
    result = await AuthorizedMultiAccountPortfolioSnapshotService(session).read(
        ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
            principal=principal,
            timestamp=baseline.timestamp,
            granularity=_GRANULARITIES[baseline.granularity],
            currency=baseline.currency,
            calculation_version=baseline.calculation_version,
            accounts=accounts,
        )
    )
    projection_duration_ms = round((perf_counter() - projection_started_at) * 1000, 2)
    _cache_result(cache_key, result)
    logger.info(
        "financial_read_phase",
        phase="published_snapshot",
        cache_hit=False,
        manifest_read_ms=baseline_duration_ms,
        projection_read_ms=projection_duration_ms,
    )
    return baseline, result


def _portfolio_response(
    baseline: DailySnapshotBaseline,
    result: ReadAuthorizedMultiAccountPortfolioSnapshotResult,
) -> CurrentPortfolioResponse:
    presentations = {item.account.account_id: item for item in result.account_presentations}
    portfolio = result.portfolio
    valuation_timestamp = result.valuation_timestamp or portfolio.timestamp
    return CurrentPortfolioResponse(
        as_of=portfolio.timestamp,
        baseline_timestamp=portfolio.timestamp,
        history_anchor_snapshot_id=baseline.net_worth_snapshot_id,
        currency=portfolio.currency,
        calculation_version=portfolio.calculation_version,
        valuation_timestamp=valuation_timestamp,
        is_stale=datetime.now(UTC).replace(tzinfo=None) - valuation_timestamp > _STALE_AFTER,
        summary=MultiAccountPortfolioSummaryResponse.model_validate(portfolio.summary),
        accounts=tuple(
            CurrentPortfolioAccountResponse(
                baseline_snapshot_id=presentations[
                    account.account.account_id
                ].presentation_snapshot_id,
                primary_baseline_snapshot_id=presentations[
                    account.account.account_id
                ].primary_snapshot_id,
                currency=presentations[account.account.account_id].currency,
                account=PortfolioSnapshotAccountResponse.model_validate(
                    presentations[account.account.account_id].account
                ),
                summary=PortfolioSnapshotSummaryResponse.model_validate(
                    presentations[account.account.account_id].summary
                ),
                positions=tuple(
                    PortfolioSnapshotPositionResponse.model_validate(position)
                    for position in presentations[account.account.account_id].positions
                ),
            )
            for account in portfolio.accounts
        ),
        aggregate_positions=tuple(
            MultiAccountPortfolioAggregatePositionResponse(
                account_id=account.account.account_id,
                account_name=account.account.name,
                account_currency=account.account.currency,
                portfolio_allocation_pct=portfolio_allocation_percentage(
                    position.value,
                    portfolio.summary.investment_value,
                ),
                position=PortfolioSnapshotPositionResponse.model_validate(position),
            )
            for account in portfolio.accounts
            for position in account.positions
        ),
    )


def _dashboard_response(
    baseline: DailySnapshotBaseline,
    result: ReadAuthorizedMultiAccountPortfolioSnapshotResult,
) -> CurrentDashboardResponse:
    dashboard = build_dashboard_snapshot_view(result.portfolio, result.account_presentations)
    valuation_timestamp = result.valuation_timestamp or dashboard.timestamp
    return CurrentDashboardResponse(
        as_of=dashboard.timestamp,
        baseline_timestamp=dashboard.timestamp,
        history_anchor_snapshot_id=baseline.net_worth_snapshot_id,
        currency=dashboard.currency,
        calculation_version=dashboard.calculation_version,
        valuation_timestamp=valuation_timestamp,
        is_stale=datetime.now(UTC).replace(tzinfo=None) - valuation_timestamp > _STALE_AFTER,
        summary=DashboardSnapshotSummaryResponse.model_validate(dashboard.summary),
        accounts=tuple(
            CurrentDashboardAccountResponse(
                account_id=account.account_id,
                baseline_snapshot_id=account.snapshot_id,
                primary_baseline_snapshot_id=account.primary_snapshot_id,
                name=account.name,
                account_type=account.account_type,
                account_currency=account.account_currency,
                output_currency=account.output_currency,
                total_value=account.total_value,
                cash_value=account.cash_value,
                investment_value=account.investment_value,
                liabilities_value=account.liabilities_value,
                net_deposits_value=account.net_deposits_value,
                unrealized_pnl_value=account.unrealized_pnl_value,
                position_count=account.position_count,
            )
            for account in dashboard.accounts
        ),
        asset_type_allocations=tuple(
            DashboardAssetTypeAllocationResponse.model_validate(item)
            for item in dashboard.asset_type_allocations
        ),
        top_positions=tuple(
            DashboardTopPositionResponse.model_validate(item) for item in dashboard.top_positions
        ),
    )


@router.post(
    "/portfolio/published", response_model=CurrentPortfolioResponse, response_model_by_alias=True
)
async def read_published_portfolio(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentPortfolioResponse:
    baseline, result = await _read_latest(
        principal=principal,
        session=session,
        account_types=_INVESTMENT_TYPES,
    )
    return _portfolio_response(baseline, result)


@router.post(
    "/dashboard/published", response_model=CurrentDashboardResponse, response_model_by_alias=True
)
async def read_published_dashboard(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentDashboardResponse:
    baseline, result = await _read_latest(principal=principal, session=session)
    return _dashboard_response(baseline, result)
