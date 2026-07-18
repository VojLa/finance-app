from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.accounts.access import require_account_access
from app.modules.portfolio.models import PortfolioSummary
from app.modules.portfolio.repository import PortfolioRepository
from app.modules.portfolio.service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummary)
async def get_portfolio(
    principal: CurrentPrincipal,
    account_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> PortfolioSummary:
    if account_id is not None:
        await require_account_access(
            session=session,
            principal=principal,
            account_id=account_id,
        )

    service = PortfolioService(PortfolioRepository(session))
    return await service.get_portfolio(user_id=principal.user_id, account_id=account_id)
