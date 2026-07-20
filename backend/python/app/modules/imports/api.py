from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.imports.models import (
    ImportBatchCreateRequest,
    ImportBatchResponse,
    ImportUploadResponse,
)
from app.modules.imports.service import ImportBatchService

router = APIRouter(prefix="/accounts/{account_id}/imports", tags=["imports"])


@router.post("", response_model=ImportBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_import_batch(
    account_id: str,
    payload: ImportBatchCreateRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportBatchResponse:
    return await ImportBatchService(session).create_batch(
        principal=principal,
        account_id=account_id,
        payload=payload,
    )


@router.get("", response_model=list[ImportBatchResponse])
async def list_import_batches(
    account_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[ImportBatchResponse]:
    return await ImportBatchService(session).list_batches(
        principal=principal,
        account_id=account_id,
    )


@router.put(
    "/{batch_id}/file",
    response_model=ImportUploadResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_import_file(
    account_id: str,
    batch_id: str,
    request: Request,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportUploadResponse:
    return await ImportBatchService(session).upload_file(
        principal=principal,
        account_id=account_id,
        batch_id=batch_id,
        content_type=request.headers.get("content-type"),
        chunks=request.stream(),
    )


@router.get("/{batch_id}", response_model=ImportBatchResponse)
async def get_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportBatchResponse:
    return await ImportBatchService(session).get_batch(
        principal=principal,
        account_id=account_id,
        batch_id=batch_id,
    )
