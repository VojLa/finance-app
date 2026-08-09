from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.categories.models import (
    CategoryCreateRequest,
    CategoryDeleteResponse,
    CategoryResponse,
    CategoryUpdateRequest,
)
from app.modules.categories.service import CategoryService
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[CategoryResponse]:
    return await CategoryService(session).list_categories(principal)


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_category(
    payload: CategoryCreateRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryResponse:
    return await CategoryService(session).create(principal=principal, payload=payload)


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    payload: CategoryUpdateRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryResponse:
    return await CategoryService(session).update(
        principal=principal,
        category_id=category_id,
        payload=payload,
    )


@router.delete("/{category_id}", response_model=CategoryDeleteResponse)
async def delete_category(
    category_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
) -> CategoryDeleteResponse:
    await CategoryService(session).delete(principal=principal, category_id=category_id)
    response.headers["Cache-Control"] = "no-store"
    return CategoryDeleteResponse(ok=True)
