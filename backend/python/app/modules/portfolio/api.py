import asyncpg
from fastapi import APIRouter, Depends, Query

from app.db.connection import get_db
from app.modules.portfolio.models import PortfolioSummary
from app.modules.portfolio.repository import PortfolioRepository
from app.modules.portfolio.service import PortfolioService


router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummary)
async def get_portfolio(
    user_id: str = Query(..., description="Temporary migration parameter until auth is shared."),
    account_id: str | None = Query(default=None),
    connection: asyncpg.Connection = Depends(get_db),
) -> PortfolioSummary:
    service = PortfolioService(PortfolioRepository(connection))
    return await service.get_portfolio(user_id=user_id, account_id=account_id)
