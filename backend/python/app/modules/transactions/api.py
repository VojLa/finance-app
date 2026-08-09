from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.db.models.enums import TransactionType
from app.modules.transactions.models import (
    TransactionCreateRequest,
    TransactionDeleteRequest,
    TransactionDeleteResponse,
    TransactionPageResponse,
    TransactionResponse,
    TransactionUpdateRequest,
)
from app.modules.transactions.service import TransactionService
from app.shared.errors import ErrorResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionPageResponse)
async def list_transactions(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    type: TransactionType | None = None,
    category_id: Annotated[str | None, Query(alias="categoryId", max_length=200)] = None,
    account_id: Annotated[str | None, Query(alias="accountId", max_length=200)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> TransactionPageResponse:
    return await TransactionService(session).list_transactions(
        principal=principal,
        page=page,
        transaction_type=type,
        category_id=category_id,
        account_id=account_id,
        search=q.strip() if q is not None else None,
    )


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_transaction(
    payload: TransactionCreateRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransactionResponse:
    return await TransactionService(session).create(principal=principal, payload=payload)


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: str,
    payload: TransactionUpdateRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransactionResponse:
    return await TransactionService(session).update(
        principal=principal,
        transaction_id=transaction_id,
        payload=payload,
    )


@router.delete("/{transaction_id}", response_model=TransactionDeleteResponse)
async def delete_transaction(
    transaction_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
    payload: TransactionDeleteRequest = Body(...),
) -> TransactionDeleteResponse:
    await TransactionService(session).delete(
        principal=principal,
        transaction_id=transaction_id,
        idempotency_key=payload.idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    return TransactionDeleteResponse(ok=True)
