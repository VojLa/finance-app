from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.budgets.models import BudgetProgressResponse, BudgetSaveRequest
from app.modules.budgets.service import BudgetService
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("/monthly", response_model=BudgetProgressResponse | None)
async def get_monthly_budget(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    month: Annotated[int, Query(ge=1, le=12)],
    year: Annotated[int, Query(ge=1970, le=9999)],
) -> BudgetProgressResponse | None:
    result = await BudgetService(session).get_progress(principal=principal, month=month, year=year)
    await session.commit()
    return result


@router.put(
    "/monthly",
    response_model=BudgetProgressResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def save_monthly_budget(
    payload: BudgetSaveRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BudgetProgressResponse:
    return await BudgetService(session).save(principal=principal, payload=payload)
