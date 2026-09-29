"""Authenticated current portfolio and dashboard HTTP adapters."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal, get_request_settings
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.modules.current_value.api_models import (
    CurrentDashboardResponse,
    CurrentPortfolioResponse,
)
from app.modules.current_value.models import CurrentPortfolioResult
from app.modules.current_value.service import (
    Clock,
    CurrentValueService,
    ReadCurrentPortfolioCommand,
    current_value_timestamp,
)
from app.modules.dashboard_snapshot.projection import build_dashboard_snapshot_view

router = APIRouter(tags=["current-value"])
_STALE_AFTER = timedelta(minutes=30)


def get_current_value_clock() -> Clock:
    return current_value_timestamp


def get_current_value_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    clock: Annotated[Clock, Depends(get_current_value_clock)],
) -> CurrentValueService:
    return CurrentValueService(session, settings, clock=clock)


def build_current_portfolio_response(
    result: CurrentPortfolioResult,
) -> CurrentPortfolioResponse:
    presentations = {item.account.account_id: item for item in result.account_presentations}
    return CurrentPortfolioResponse(
        as_of=result.as_of,
        baseline_timestamp=result.baseline_timestamp,
        history_anchor_snapshot_id=result.baseline_net_worth_snapshot_id,
        currency=result.portfolio.currency,
        calculation_version=result.portfolio.calculation_version,
        valuation_timestamp=result.as_of,
        is_stale=datetime.now(UTC).replace(tzinfo=None) - result.as_of > _STALE_AFTER,
        summary=result.portfolio.summary,
        accounts=tuple(
            {
                "baseline_snapshot_id": presentations[
                    account.account.account_id
                ].presentation_snapshot_id,
                "primary_baseline_snapshot_id": presentations[
                    account.account.account_id
                ].primary_snapshot_id,
                "currency": presentations[account.account.account_id].currency,
                "account": presentations[account.account.account_id].account,
                "summary": presentations[account.account.account_id].summary,
                "positions": presentations[account.account.account_id].positions,
            }
            for account in result.portfolio.accounts
        ),
        aggregate_positions=tuple(
            {
                "account_id": account.account.account_id,
                "account_name": account.account.name,
                "account_currency": account.account.currency,
                "position": position,
            }
            for account in result.portfolio.accounts
            for position in account.positions
        ),
    )


def build_current_dashboard_response(
    result: CurrentPortfolioResult,
) -> CurrentDashboardResponse:
    dashboard = build_dashboard_snapshot_view(
        result.portfolio,
        result.account_presentations,
    )
    return CurrentDashboardResponse(
        as_of=result.as_of,
        baseline_timestamp=result.baseline_timestamp,
        history_anchor_snapshot_id=result.baseline_net_worth_snapshot_id,
        currency=dashboard.currency,
        calculation_version=dashboard.calculation_version,
        valuation_timestamp=result.as_of,
        is_stale=datetime.now(UTC).replace(tzinfo=None) - result.as_of > _STALE_AFTER,
        summary=dashboard.summary,
        accounts=tuple(
            {
                "account_id": account.account_id,
                "baseline_snapshot_id": account.snapshot_id,
                "primary_baseline_snapshot_id": account.primary_snapshot_id,
                "name": account.name,
                "account_type": account.account_type,
                "account_currency": account.account_currency,
                "output_currency": account.output_currency,
                "total_value": account.total_value,
                "cash_value": account.cash_value,
                "investment_value": account.investment_value,
                "liabilities_value": account.liabilities_value,
                "net_deposits_value": account.net_deposits_value,
                "unrealized_pnl_value": account.unrealized_pnl_value,
                "position_count": account.position_count,
            }
            for account in dashboard.accounts
        ),
        asset_type_allocations=dashboard.asset_type_allocations,
        top_positions=dashboard.top_positions,
    )


@router.post(
    "/portfolio/current",
    response_model=CurrentPortfolioResponse,
    response_model_by_alias=True,
    deprecated=True,
)
async def read_current_portfolio(
    principal: CurrentPrincipal,
    service: Annotated[CurrentValueService, Depends(get_current_value_service)],
) -> CurrentPortfolioResponse:
    return build_current_portfolio_response(
        await service.read_investment_portfolio(ReadCurrentPortfolioCommand(principal=principal))
    )


@router.post(
    "/dashboard/current",
    response_model=CurrentDashboardResponse,
    response_model_by_alias=True,
    deprecated=True,
)
async def read_current_dashboard(
    principal: CurrentPrincipal,
    service: Annotated[CurrentValueService, Depends(get_current_value_service)],
) -> CurrentDashboardResponse:
    return build_current_dashboard_response(
        await service.read_portfolio(ReadCurrentPortfolioCommand(principal=principal))
    )
