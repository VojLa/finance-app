"""Authorized transaction boundary for public Holding rebuilds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.common import TIMESTAMP
from app.db.models.enums import AccountMemberRole
from app.modules.accounts.access import require_account_access
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.projection import HoldingProjectionStateError
from app.modules.holdings.rebuild_service import (
    HoldingRebuildService,
    HoldingRebuildStateError,
)
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}
Clock = Callable[[], datetime]


class HoldingRebuildUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="holding_rebuild_unavailable",
            message="Holdings cannot be rebuilt from the current canonical history.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class RebuildHoldingsCommand:
    principal: AuthenticatedPrincipal
    account_id: str


def current_rebuild_timestamp() -> datetime:
    return datetime.now(UTC)


def normalize_rebuild_timestamp(value: datetime) -> datetime:
    precision = TIMESTAMP.precision
    if precision is None or not 0 <= precision <= 6:
        raise RuntimeError("Canonical TIMESTAMP precision must be between zero and six.")
    normalized = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    unit = 10 ** (6 - precision)
    return normalized.replace(microsecond=normalized.microsecond - (normalized.microsecond % unit))


class HoldingRebuildApplicationService:
    def __init__(self, session: AsyncSession, *, clock: Clock = current_rebuild_timestamp) -> None:
        self.session = session
        self.clock = clock

    async def rebuild(self, command: RebuildHoldingsCommand) -> HoldingRebuildResponse:
        try:
            # The membership row remains locked through commit. A concurrent role
            # downgrade or removal therefore either commits first and is observed,
            # or waits until this rebuild transaction completes.
            await require_account_access(
                session=self.session,
                principal=command.principal,
                account_id=command.account_id,
                allowed_roles=WRITE_ROLES,
                for_update=True,
            )
            rebuilt_at = normalize_rebuild_timestamp(self.clock())
            result = await HoldingRebuildService(self.session).rebuild(
                account_id=command.account_id,
                rebuilt_at=rebuilt_at,
            )
            response = HoldingRebuildResponse(
                account_id=result.account_id,
                created=result.created,
                updated=result.updated,
                deleted=result.deleted,
                total=result.total,
                replayed=result.replayed,
                rebuilt_at=result.rebuilt_at,
            )
            await self.session.commit()
        except (HoldingProjectionStateError, HoldingRebuildStateError) as exc:
            await self.session.rollback()
            raise HoldingRebuildUnavailableError() from exc
        except Exception:
            await self.session.rollback()
            raise
        return response
