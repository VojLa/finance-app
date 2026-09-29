from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.modules.jobs.models import ImportJobResponse, ImportJobStartRequest
from app.modules.jobs.service import BackgroundJobService, EnqueueImportJobCommand

router = APIRouter(prefix="/accounts/{account_id}/imports/jobs", tags=["background-jobs"])


@router.post("", response_model=ImportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_import_job(
    account_id: str,
    payload: ImportJobStartRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportJobResponse:
    result = await BackgroundJobService(session).enqueue_import_job(
        EnqueueImportJobCommand(
            principal=principal, account_id=account_id, batch_ids=payload.batch_ids
        )
    )
    return BackgroundJobService.public_response(result.job)


@router.get("/{job_id}", response_model=ImportJobResponse)
async def get_import_job(
    account_id: str,
    job_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportJobResponse:
    return await BackgroundJobService(session).get_import_job(
        principal=principal, account_id=account_id, job_id=job_id
    )


@router.post("/{job_id}/retry", response_model=ImportJobResponse)
async def retry_import_job(
    account_id: str,
    job_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportJobResponse:
    return await BackgroundJobService(session).retry_import_job(
        principal=principal, account_id=account_id, job_id=job_id
    )
