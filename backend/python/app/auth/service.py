from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import (
    BaseCurrencyChangeUnavailableError,
    CurrentPasswordInvalidError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidSessionTokenError,
)
from app.auth.models import (
    AuthenticatedPrincipal,
    AuthenticatedUserResponse,
    BaseCurrencyChangeRequest,
    BaseCurrencyChangeResponse,
    CredentialVerificationRequest,
    PasswordChangeRequest,
    UserRegistrationRequest,
)
from app.auth.repository import AuthRepository
from app.db.models.users import UserModel
from app.modules.market_data.source_policy import MarketEvidenceSourcePolicy
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
    PortfolioHistoryInvalidationStateError,
)

DUMMY_PASSWORD_HASH = "$2b$12$J8Ufcs38lSf/xbQcSXw8ouVpLX3WKTJsUDRBQTMjgpN2Lrx1Sh0.."


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _history_now() -> datetime:
    value = _now()
    return value.replace(microsecond=value.microsecond // 1_000 * 1_000)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def _password_matches(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        source_policy: MarketEvidenceSourcePolicy | None = None,
        history: PortfolioHistoryInvalidationService | None = None,
    ) -> None:
        self.session = session
        self.repository = AuthRepository(session)
        self.history = history or PortfolioHistoryInvalidationService(
            session,
            source_policy=source_policy,
        )

    async def verify_credentials(
        self,
        payload: CredentialVerificationRequest,
    ) -> AuthenticatedUserResponse:
        user = await self.repository.find_by_email(payload.email)
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        password_matches = _password_matches(payload.password, password_hash)
        if user is None or not password_matches:
            await self._close_read_transaction()
            raise InvalidCredentialsError()

        response = self._response(user)
        await self._close_read_transaction()
        return response

    async def register(self, payload: UserRegistrationRequest) -> AuthenticatedUserResponse:
        if await self.repository.find_by_email(payload.email) is not None:
            await self.session.rollback()
            raise EmailAlreadyRegisteredError()

        now = _now()
        user = UserModel(
            id=str(uuid4()),
            email=payload.email,
            name=payload.name,
            password_hash=_hash_password(payload.password),
            base_currency="CZK",
            created_at=now,
            updated_at=now,
        )
        self.repository.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise EmailAlreadyRegisteredError() from exc
        except Exception:
            await self.session.rollback()
            raise
        return self._response(user)

    async def change_password(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: PasswordChangeRequest,
    ) -> None:
        user = await self.repository.find_by_id_for_update(principal.user_id)
        if user is None or not _password_matches(payload.current_password, user.password_hash):
            await self.session.rollback()
            raise CurrentPasswordInvalidError()

        user.password_hash = _hash_password(payload.new_password)
        user.updated_at = _now()
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def change_base_currency(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: BaseCurrencyChangeRequest,
    ) -> BaseCurrencyChangeResponse:
        """Change the aggregate currency and dirty history in one owned transaction."""

        await self.session.begin()
        try:
            await self.history.lock_generation_users((principal.user_id,))
            user = await self.repository.find_by_id_for_update(principal.user_id)
            if user is None or user.id != principal.user_id:
                raise InvalidSessionTokenError()
            if user.base_currency == payload.base_currency:
                await self.session.commit()
                return BaseCurrencyChangeResponse(base_currency=user.base_currency)

            now = _history_now()
            user.base_currency = payload.base_currency
            user.updated_at = now
            await self.session.flush()
            await self.history.invalidate_scope_users(
                user_ids=(principal.user_id,),
                now=now,
            )
            await self.session.commit()
            return BaseCurrencyChangeResponse(base_currency=user.base_currency)
        except PortfolioHistoryInvalidationStateError as exc:
            await self.session.rollback()
            raise BaseCurrencyChangeUnavailableError() from exc
        except Exception:
            await self.session.rollback()
            raise

    async def _close_read_transaction(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _response(user: UserModel) -> AuthenticatedUserResponse:
        return AuthenticatedUserResponse(id=user.id, email=user.email, name=user.name)
