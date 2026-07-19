from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.accounts.models import AccountCreateRequest, AccountResponse, AccountUpdateRequest
from app.modules.accounts.service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[AccountResponse]:
    return await AccountService(session).list_accounts(principal)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).create_account(principal=principal, payload=payload)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    payload: AccountUpdateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> AccountResponse:
    return await AccountService(session).update_account(
        principal=principal,
        account_id=account_id,
        payload=payload,
    )
