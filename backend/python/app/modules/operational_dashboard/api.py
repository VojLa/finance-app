from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.operational_dashboard.models import OperationalDashboardResponse
from app.modules.operational_dashboard.service import OperationalDashboardService
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/operational-dashboard", tags=["operational-dashboard"])


@router.get(
    "", response_model=OperationalDashboardResponse, responses={409: {"model": ErrorResponse}}
)
async def get_operational_dashboard(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OperationalDashboardResponse:
    result = await OperationalDashboardService(session).read(principal=principal)
    await session.commit()
    return result
