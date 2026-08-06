"""Explicit immutable onboarding for exact provider-owned AssetAlias rows."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetAliasModel, AssetModel
from app.db.models.enums import AssetAliasProvider
from app.modules.asset_aliases.identity import (
    provider_asset_types,
    validate_onboard_asset_alias_command,
)
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasInvalidError,
    AssetAliasNotFoundError,
    AssetAliasOnboardingDisposition,
    AssetAliasStateError,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
    UnresolvedAssetAlias,
)
from app.modules.asset_aliases.repository import (
    AssetAliasReadRepository,
    AssetAliasWriterRepository,
    asset_provider_lock_scope,
    provider_external_lock_scope,
)

ASSET_ALIAS_NAMESPACE = UUID("b1d66d76-35f0-4db0-b1d9-0f5452d4a27c")
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}


class _StateRepository(Protocol):
    async def load_asset(self, asset_id: str) -> AssetModel | None: ...

    async def load_asset_provider_aliases(
        self,
        asset_id: str,
        provider: AssetAliasProvider,
    ) -> tuple[AssetAliasModel, ...]: ...

    async def load_provider_external_alias(
        self,
        provider: AssetAliasProvider,
        external_id: str,
    ) -> AssetAliasModel | None: ...

    async def load_alias_by_id(self, alias_id: str) -> AssetAliasModel | None: ...


class _ReadRepository(_StateRepository, Protocol):
    async def set_transaction_read_only(self) -> None: ...


class _InventoryRepository(Protocol):
    async def set_transaction_read_only(self) -> None: ...

    async def list_unresolved(
        self,
        provider: AssetAliasProvider,
    ) -> tuple[UnresolvedAssetAlias, ...]: ...


class _WriterRepository(_StateRepository, Protocol):
    async def set_transaction_serializable(self) -> None: ...

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None: ...

    def add_alias(self, row: AssetAliasModel) -> None: ...

    async def flush(self) -> None: ...

    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None: ...


class _Writer(Protocol):
    async def write(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult: ...


def asset_alias_id(asset_id: str, provider: AssetAliasProvider) -> str:
    return str(uuid5(ASSET_ALIAS_NAMESPACE, f"{asset_id}\0{provider.value}"))


def _timestamp_is_exact(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is None and value.microsecond % 1_000 == 0


def _target_matches(asset: object, command: OnboardAssetAliasCommand) -> bool:
    return (
        isinstance(asset, AssetModel)
        and asset.id == command.asset_id
        and asset.symbol == command.expected_symbol
        and asset.asset_type is command.expected_asset_type
        and asset.currency == command.expected_currency
        and (command.expected_isin is None or asset.isin == command.expected_isin)
        and asset.asset_type in provider_asset_types(command.provider)
    )


def _alias_shape_is_valid(row: object) -> bool:
    return (
        isinstance(row, AssetAliasModel)
        and isinstance(row.id, str)
        and bool(row.id)
        and isinstance(row.asset_id, str)
        and bool(row.asset_id)
        and isinstance(row.provider, AssetAliasProvider)
        and isinstance(row.external_id, str)
        and bool(row.external_id)
        and _timestamp_is_exact(row.created_at)
    )


def _created_row_matches(
    row: object,
    command: OnboardAssetAliasCommand,
    expected_id: str,
) -> bool:
    return (
        isinstance(row, AssetAliasModel)
        and _alias_shape_is_valid(row)
        and row.id == expected_id
        and row.asset_id == command.asset_id
        and row.provider is command.provider
        and row.external_id == command.external_id
        and row.created_at == command.created_at
    )


def _assess_existing_state(
    *,
    command: OnboardAssetAliasCommand,
    asset: AssetModel | None,
    aliases: tuple[AssetAliasModel, ...],
    external_alias: AssetAliasModel | None,
    id_alias: AssetAliasModel | None,
) -> AssetAliasModel | None:
    if asset is None:
        raise AssetAliasNotFoundError()
    if not _target_matches(asset, command):
        raise AssetAliasConflictError()
    if len(aliases) > 1:
        raise AssetAliasStateError()
    if len(aliases) == 1:
        existing = aliases[0]
        if not _alias_shape_is_valid(existing):
            raise AssetAliasStateError()
        if (
            existing.asset_id == command.asset_id
            and existing.provider is command.provider
            and existing.external_id == command.external_id
        ):
            return existing
        raise AssetAliasConflictError()
    if external_alias is not None:
        if not _alias_shape_is_valid(external_alias):
            raise AssetAliasStateError()
        raise AssetAliasConflictError()
    if id_alias is not None:
        if not _alias_shape_is_valid(id_alias):
            raise AssetAliasStateError()
        raise AssetAliasConflictError()
    return None


async def _load_state(
    repository: _StateRepository,
    command: OnboardAssetAliasCommand,
) -> tuple[
    AssetModel | None,
    tuple[AssetAliasModel, ...],
    AssetAliasModel | None,
    AssetAliasModel | None,
]:
    expected_id = asset_alias_id(command.asset_id, command.provider)
    return (
        await repository.load_asset(command.asset_id),
        await repository.load_asset_provider_aliases(
            command.asset_id,
            command.provider,
        ),
        await repository.load_provider_external_alias(
            command.provider,
            command.external_id,
        ),
        await repository.load_alias_by_id(expected_id),
    )


def _sqlstate(error: BaseException) -> str | None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str):
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


class AssetAliasWriter:
    """Own one complete create/replay SERIALIZABLE attempt."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _WriterRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or AssetAliasWriterRepository(session)

    async def write(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult:
        canonical = validate_onboard_asset_alias_command(command)
        if self.session.in_transaction():
            raise AssetAliasStateError()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    result = await self._write_attempt(canonical)
            except (
                AssetAliasConflictError,
                AssetAliasInvalidError,
                AssetAliasNotFoundError,
                AssetAliasStateError,
            ):
                if self.session.in_transaction():
                    await self.session.rollback()
                raise
            except SQLAlchemyError as exc:
                if self.session.in_transaction():
                    await self.session.rollback()
                if (
                    _sqlstate(exc) in _RETRYABLE_SQLSTATES
                    and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise AssetAliasDatabaseUnavailableError() from exc
            if self.session.in_transaction():
                await self.session.rollback()
                raise AssetAliasStateError()
            return result
        raise AssetAliasDatabaseUnavailableError()

    async def _write_attempt(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult:
        await self.repository.set_transaction_serializable()
        scopes = tuple(
            sorted(
                (
                    asset_provider_lock_scope(command.asset_id, command.provider),
                    provider_external_lock_scope(
                        command.provider,
                        command.external_id,
                    ),
                )
            )
        )
        await self.repository.acquire_identity_locks(scopes)
        asset, aliases, external_alias, id_alias = await _load_state(
            self.repository,
            command,
        )
        existing = _assess_existing_state(
            command=command,
            asset=asset,
            aliases=aliases,
            external_alias=external_alias,
            id_alias=id_alias,
        )
        if existing is not None:
            return OnboardAssetAliasResult(
                alias_id=existing.id,
                asset_id=command.asset_id,
                provider=command.provider,
                external_id=command.external_id,
                disposition=AssetAliasOnboardingDisposition.replayed,
            )

        expected_id = asset_alias_id(command.asset_id, command.provider)
        self.repository.add_alias(
            AssetAliasModel(
                id=expected_id,
                asset_id=command.asset_id,
                provider=command.provider,
                external_id=command.external_id,
                created_at=command.created_at,
            )
        )
        await self.repository.flush()
        persisted = await self.repository.reload_alias(expected_id)
        if not _created_row_matches(persisted, command, expected_id):
            raise AssetAliasStateError()
        return OnboardAssetAliasResult(
            alias_id=expected_id,
            asset_id=command.asset_id,
            provider=command.provider,
            external_id=command.external_id,
            disposition=AssetAliasOnboardingDisposition.created,
        )


class AssetAliasOnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        read_repository: _ReadRepository | None = None,
        writer: _Writer | None = None,
    ) -> None:
        self.session = session
        self.read_repository = read_repository or AssetAliasReadRepository(session)
        self.writer = writer or AssetAliasWriter(session)

    async def onboard(
        self,
        command: OnboardAssetAliasCommand,
        *,
        dry_run: bool = False,
    ) -> OnboardAssetAliasResult:
        canonical = validate_onboard_asset_alias_command(command)
        if type(dry_run) is not bool:
            raise AssetAliasInvalidError()
        if self.session.in_transaction():
            raise AssetAliasStateError()
        if not dry_run:
            result = await self.writer.write(canonical)
            if self.session.in_transaction():
                await self.session.rollback()
                raise AssetAliasStateError()
            return result

        async with self.session.begin():
            await self.read_repository.set_transaction_read_only()
            asset, aliases, external_alias, id_alias = await _load_state(
                self.read_repository,
                canonical,
            )
            _assess_existing_state(
                command=canonical,
                asset=asset,
                aliases=aliases,
                external_alias=external_alias,
                id_alias=id_alias,
            )
        if self.session.in_transaction():
            await self.session.rollback()
            raise AssetAliasStateError()
        return OnboardAssetAliasResult(
            alias_id=None,
            asset_id=canonical.asset_id,
            provider=canonical.provider,
            external_id=canonical.external_id,
            disposition=AssetAliasOnboardingDisposition.dry_run,
        )


class AssetAliasInventoryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _InventoryRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or AssetAliasReadRepository(session)

    async def list_unresolved(
        self,
        provider: AssetAliasProvider,
    ) -> tuple[UnresolvedAssetAlias, ...]:
        if not isinstance(provider, AssetAliasProvider):
            raise AssetAliasInvalidError()
        provider_asset_types(provider)
        if self.session.in_transaction():
            raise AssetAliasStateError()
        async with self.session.begin():
            await self.repository.set_transaction_read_only()
            result = await self.repository.list_unresolved(provider)
        if self.session.in_transaction():
            await self.session.rollback()
            raise AssetAliasStateError()
        return result


__all__ = [
    "ASSET_ALIAS_NAMESPACE",
    "AssetAliasInventoryService",
    "AssetAliasOnboardingService",
    "AssetAliasWriter",
    "asset_alias_id",
]
