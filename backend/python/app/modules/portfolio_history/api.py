"""Authenticated HTTP adapter for snapshot-backed portfolio history."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.portfolio_history.api_models import PortfolioHistoryResponse
from app.modules.portfolio_history.models import PortfolioHistoryRange
from app.modules.portfolio_history.service import (
    Clock,
    ReadPortfolioHistoryCommand,
    SnapshotBackedPortfolioHistoryService,
    current_portfolio_history_timestamp,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio-history"])


def get_portfolio_history_clock() -> Clock:
    return current_portfolio_history_timestamp


def get_snapshot_backed_portfolio_history_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    clock: Annotated[Clock, Depends(get_portfolio_history_clock)],
) -> SnapshotBackedPortfolioHistoryService:
    return SnapshotBackedPortfolioHistoryService(session, clock=clock)


@router.get(
    "/history",
    response_model=PortfolioHistoryResponse,
    response_model_by_alias=True,
)
async def read_portfolio_history(
    principal: CurrentPrincipal,
    service: Annotated[
        SnapshotBackedPortfolioHistoryService,
        Depends(get_snapshot_backed_portfolio_history_service),
    ],
    history_range: Annotated[
        PortfolioHistoryRange,
        Query(alias="range"),
    ] = PortfolioHistoryRange.one_year,
) -> PortfolioHistoryResponse:
    result = await service.read(
        ReadPortfolioHistoryCommand(
            principal=principal,
            range=history_range,
        )
    )
    return PortfolioHistoryResponse.model_validate(result.history, from_attributes=True)
