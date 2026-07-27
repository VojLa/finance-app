"""Thin public HTTP adapter for Holding rebuild orchestration."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import (
    HoldingRebuildApplicationService,
    RebuildHoldingsCommand,
)

router = APIRouter(prefix="/accounts/{account_id}/holdings", tags=["holdings"])


@router.post("/rebuild", response_model=HoldingRebuildResponse)
async def rebuild_holdings(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> HoldingRebuildResponse:
    return await HoldingRebuildApplicationService(session).rebuild(
        RebuildHoldingsCommand(principal=principal, account_id=account_id)
    )
