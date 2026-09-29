"""Authenticated HTTP adapter for published portfolio snapshot history."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.portfolio_snapshot.history_api_models import PortfolioHistoryResponse
from app.modules.portfolio_snapshot.history_contracts import HistoryPublicRange
from app.modules.portfolio_snapshot.history_reader import PublishedPortfolioSnapshotHistoryReader

router = APIRouter(prefix="/portfolio", tags=["portfolio-history"])


def get_published_portfolio_snapshot_history_reader(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublishedPortfolioSnapshotHistoryReader:
    return PublishedPortfolioSnapshotHistoryReader(session)


@router.get(
    "/history",
    response_model=PortfolioHistoryResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
)
async def read_portfolio_history(
    principal: CurrentPrincipal,
    reader: Annotated[
        PublishedPortfolioSnapshotHistoryReader,
        Depends(get_published_portfolio_snapshot_history_reader),
    ],
    history_range: Annotated[
        HistoryPublicRange,
        Query(alias="range"),
    ] = HistoryPublicRange.one_year,
    account_id: Annotated[str | None, Query(alias="accountId")] = None,
) -> PortfolioHistoryResponse:
    return await reader.read(
        principal=principal,
        history_range=history_range,
        account_id=account_id,
    )
