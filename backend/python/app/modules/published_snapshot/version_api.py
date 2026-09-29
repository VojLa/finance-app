"""Lightweight authorized version check for published financial read models."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentPrincipal
from app.db.connection import get_db_session
from app.db.models.canonical_lineage import UserReadModelPublicationModel

router = APIRouter(tags=["published-snapshot"])

_SCOPES = ("portfolio", "dashboard")


class ReadModelVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=255)
    scopes: tuple[str, ...]


def _after(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip() or len(value) > 255 or "\0" in value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


@router.get("/read-model-version", response_model=ReadModelVersionResponse)
async def read_model_version(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    after: Annotated[str | None, Query()] = None,
) -> ReadModelVersionResponse | Response:
    expected = _after(after)
    publication = await session.get(UserReadModelPublicationModel, principal.user_id)
    if publication is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    if expected == publication.version:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    scopes = tuple(scope for scope in publication.scopes if scope in _SCOPES)
    if not scopes:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return ReadModelVersionResponse(version=publication.version, scopes=scopes)
