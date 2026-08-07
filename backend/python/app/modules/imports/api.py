from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal, get_request_settings
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.models import (
    FinalizeImportBatchesRequest,
    FinalizeImportBatchesResponse,
    ImportBatchCreateRequest,
    ImportBatchResponse,
    ImportCanonicalPostResponse,
    ImportClassifyResponse,
    ImportDeduplicateResponse,
    ImportNormalizeResponse,
    ImportParseResponse,
    ImportPostResponse,
    ImportSnapshotRefreshStatus,
    ImportUploadResponse,
)
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    ImportMultiFileFinalizationService,
)
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.post_processing_service import ImportBatchPostProcessingService
from app.modules.imports.posting_service import ImportBatchPostingService, PostImportBatchCommand
from app.modules.imports.processing import ImportParserService
from app.modules.imports.service import ImportBatchService
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)

router = APIRouter(prefix="/accounts/{account_id}/imports", tags=["imports"])


def get_import_market_backed_snapshot_refresh_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_request_settings),
) -> MarketBackedSnapshotRefreshService:
    return MarketBackedSnapshotRefreshService(session, settings)


def get_import_batch_post_processing_service(
    session: AsyncSession = Depends(get_db_session),
    market_backed_service: MarketBackedSnapshotRefreshService = Depends(
        get_import_market_backed_snapshot_refresh_service
    ),
) -> ImportBatchPostProcessingService:
    return ImportBatchPostProcessingService(
        session,
        market_backed_service=market_backed_service,
    )


def get_import_multi_file_finalization_service(
    session: AsyncSession = Depends(get_db_session),
    market_backed_service: MarketBackedSnapshotRefreshService = Depends(
        get_import_market_backed_snapshot_refresh_service
    ),
) -> ImportMultiFileFinalizationService:
    return ImportMultiFileFinalizationService(
        session,
        market_backed_service=market_backed_service,
    )


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


@router.post("/{batch_id}/parse", response_model=ImportParseResponse)
async def parse_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportParseResponse:
    return await ImportParserService(session).parse_batch(
        principal=principal,
        account_id=account_id,
        batch_id=batch_id,
    )


@router.post("/{batch_id}/normalize", response_model=ImportNormalizeResponse)
async def normalize_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportNormalizeResponse:
    return await ImportNormalizationService(session).normalize_batch(
        principal=principal,
        account_id=account_id,
        batch_id=batch_id,
    )


@router.post("/{batch_id}/deduplicate", response_model=ImportDeduplicateResponse)
async def deduplicate_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportDeduplicateResponse:
    return await ImportDeduplicationService(session).deduplicate_batch(
        principal=principal,
        account_id=account_id,
        batch_id=batch_id,
    )


@router.post("/{batch_id}/classify", response_model=ImportClassifyResponse)
async def classify_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportClassifyResponse:
    return await ImportClassificationService(session).classify_batch(
        principal=principal, account_id=account_id, batch_id=batch_id
    )


@router.post("/{batch_id}/post", response_model=ImportPostResponse)
async def post_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    service: ImportBatchPostProcessingService = Depends(get_import_batch_post_processing_service),
) -> ImportPostResponse:
    return await service.post_batch(
        PostImportBatchCommand(
            principal=principal,
            account_id=account_id,
            batch_id=batch_id,
        )
    )


@router.post("/{batch_id}/canonical-post", response_model=ImportCanonicalPostResponse)
async def canonical_post_import_batch(
    account_id: str,
    batch_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ImportCanonicalPostResponse:
    result = await ImportBatchPostingService(session).post_batch(
        PostImportBatchCommand(
            principal=principal,
            account_id=account_id,
            batch_id=batch_id,
        )
    )
    return ImportCanonicalPostResponse(
        batch_id=result.batch_id,
        status=result.status,
        rows_total=result.rows_total,
        rows_imported=result.rows_imported,
        rows_skipped=result.rows_skipped,
        completed_at=result.completed_at,
        replayed=result.replayed,
    )


@router.post("/finalize", response_model=FinalizeImportBatchesResponse)
async def finalize_import_batches(
    account_id: str,
    payload: FinalizeImportBatchesRequest,
    principal: CurrentPrincipal,
    service: ImportMultiFileFinalizationService = Depends(
        get_import_multi_file_finalization_service
    ),
) -> FinalizeImportBatchesResponse:
    if not payload.batch_ids:
        return FinalizeImportBatchesResponse(
            batch_ids=(),
            snapshot_refresh_status=ImportSnapshotRefreshStatus.not_required,
        )
    result = await service.finalize(
        FinalizeImportBatchesCommand(
            principal=principal,
            account_id=account_id,
            batch_ids=tuple(sorted(payload.batch_ids)),
        )
    )
    return FinalizeImportBatchesResponse(
        batch_ids=result.batch_ids,
        snapshot_refresh_status=result.snapshot_refresh_status,
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
