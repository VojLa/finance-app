"""Explicit immutable onboarding for exact provider-owned AssetAlias rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.asset_alias_audit import AssetAliasAuditModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import AssetAliasProvider, PriceSource
from app.modules.asset_aliases.identity import (
    provider_asset_types,
    validate_create_asset_listing_command,
    validate_onboard_asset_alias_command,
    validate_reject_asset_alias_command,
)
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasInvalidError,
    AssetAliasNotFoundError,
    AssetAliasOnboardingDisposition,
    AssetAliasStateError,
    CreateAssetListingCommand,
    CreateAssetListingResult,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
    RejectAssetAliasCommand,
    RejectAssetAliasResult,
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

    async def load_listing(self, listing_id: str) -> AssetListingModel | None: ...

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

    async def load_provider_listings(
        self, provider: PriceSource, provider_symbol: str
    ) -> tuple[AssetListingModel, ...]: ...


class _ReadRepository(_StateRepository, Protocol):
    async def set_transaction_read_only(self) -> None: ...


class _InventoryRepository(Protocol):
    async def set_transaction_read_only(self) -> None: ...

    async def list_unresolved(
        self,
        provider: AssetAliasProvider,
    ) -> tuple[UnresolvedAssetAlias, ...]: ...

    async def health_summary(
        self, provider: AssetAliasProvider, *, as_of: datetime
    ) -> dict[str, object]: ...


class _WriterRepository(_StateRepository, Protocol):
    async def set_transaction_serializable(self) -> None: ...

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None: ...

    def add_alias(self, row: AssetAliasModel) -> None: ...

    def add_audit(self, row: AssetAliasAuditModel) -> None: ...

    def add_listing(self, row: AssetListingModel) -> None: ...

    async def flush(self) -> None: ...

    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None: ...


class _Writer(Protocol):
    async def write(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult: ...


def asset_alias_id(
    asset_id: str, provider: AssetAliasProvider, listing_id: str | None = None
) -> str:
    identity = f"{asset_id}\0{provider.value}"
    if listing_id is not None:
        identity += f"\0{listing_id}"
    return str(uuid5(ASSET_ALIAS_NAMESPACE, identity))


def _timestamp_is_exact(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is None and value.microsecond % 1_000 == 0


def _audit_alias(
    repository: _WriterRepository,
    command: OnboardAssetAliasCommand,
    row: AssetAliasModel,
    *,
    replayed: bool,
) -> None:
    identity = {
        "aliasId": row.id,
        "assetId": row.asset_id,
        "listingId": row.listing_id,
        "provider": row.provider.value,
        "externalId": row.external_id,
    }
    repository.add_audit(
        AssetAliasAuditModel(
            id=str(uuid4()),
            actor=command.actor,
            action="alias_replayed" if replayed else "alias_created",
            asset_id=command.asset_id,
            listing_id=command.listing_id,
            provider=command.provider.value,
            external_id=command.external_id,
            before_identity=identity if replayed else None,
            after_identity=identity,
            reason=None,
        )
    )


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
        and (row.listing_id is None or (isinstance(row.listing_id, str) and bool(row.listing_id)))
        and isinstance(row.provider, AssetAliasProvider)
        and isinstance(row.external_id, str)
        and bool(row.external_id)
        and _timestamp_is_exact(row.created_at)
    )


def _same_physical_alias(
    left: AssetAliasModel,
    right: AssetAliasModel,
) -> bool:
    return (
        _alias_shape_is_valid(left)
        and _alias_shape_is_valid(right)
        and left.id == right.id
        and left.asset_id == right.asset_id
        and left.listing_id == right.listing_id
        and left.provider is right.provider
        and left.external_id == right.external_id
        and left.created_at == right.created_at
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
        and row.listing_id == command.listing_id
        and row.provider is command.provider
        and row.external_id == command.external_id
        and row.created_at == command.created_at
    )


async def _reject_direct_identity_collision(
    repository: _StateRepository, command: OnboardAssetAliasCommand
) -> None:
    direct = await repository.load_provider_listings(
        PriceSource(command.provider.value), command.external_id
    )
    if any(
        listing.asset_id != command.asset_id
        or (command.listing_id is not None and listing.id != command.listing_id)
        for listing in direct
    ):
        raise AssetAliasConflictError()


def _assess_existing_state(
    *,
    command: OnboardAssetAliasCommand,
    asset: AssetModel | None,
    listing: AssetListingModel | None,
    aliases: tuple[AssetAliasModel, ...],
    external_alias: AssetAliasModel | None,
    id_alias: AssetAliasModel | None,
) -> AssetAliasModel | None:
    if asset is None:
        raise AssetAliasNotFoundError()
    if not _target_matches(asset, command):
        raise AssetAliasConflictError()
    if command.listing_id is not None:
        if listing is None:
            raise AssetAliasNotFoundError()
        if listing.asset_id != command.asset_id or (
            listing.provider is PriceSource(command.provider.value)
            and listing.provider_symbol is not None
            and listing.provider_symbol != command.external_id
        ):
            raise AssetAliasConflictError()
    if any(
        (row.listing_id is None and command.listing_id is not None)
        or (row.listing_id is not None and command.listing_id is None)
        for row in aliases
    ):
        raise AssetAliasConflictError()
    target_aliases = tuple(row for row in aliases if row.listing_id == command.listing_id)
    if len(target_aliases) > 1:
        raise AssetAliasStateError()
    if len(target_aliases) == 1:
        existing = target_aliases[0]
        if not _alias_shape_is_valid(existing):
            raise AssetAliasStateError()
        if (
            existing.asset_id == command.asset_id
            and existing.listing_id == command.listing_id
            and existing.provider is command.provider
            and existing.external_id == command.external_id
        ):
            if external_alias is None:
                raise AssetAliasStateError()
            if not _alias_shape_is_valid(external_alias):
                raise AssetAliasStateError()
            if not _same_physical_alias(existing, external_alias):
                raise AssetAliasConflictError()
            expected_id = asset_alias_id(command.asset_id, command.provider, command.listing_id)
            if id_alias is None:
                if existing.id == expected_id:
                    raise AssetAliasStateError()
            else:
                if not _alias_shape_is_valid(id_alias):
                    raise AssetAliasStateError()
                if not _same_physical_alias(existing, id_alias):
                    raise AssetAliasConflictError()
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
    AssetListingModel | None,
    tuple[AssetAliasModel, ...],
    AssetAliasModel | None,
    AssetAliasModel | None,
]:
    expected_id = asset_alias_id(command.asset_id, command.provider, command.listing_id)
    return (
        await repository.load_asset(command.asset_id),
        await repository.load_listing(command.listing_id) if command.listing_id else None,
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
        asset, listing, aliases, external_alias, id_alias = await _load_state(
            self.repository,
            command,
        )
        await _reject_direct_identity_collision(self.repository, command)
        existing = _assess_existing_state(
            command=command,
            asset=asset,
            listing=listing,
            aliases=aliases,
            external_alias=external_alias,
            id_alias=id_alias,
        )
        if existing is not None:
            _audit_alias(self.repository, command, existing, replayed=True)
            return OnboardAssetAliasResult(
                alias_id=existing.id,
                asset_id=command.asset_id,
                provider=command.provider,
                external_id=command.external_id,
                disposition=AssetAliasOnboardingDisposition.replayed,
            )

        expected_id = asset_alias_id(command.asset_id, command.provider, command.listing_id)
        self.repository.add_alias(
            AssetAliasModel(
                id=expected_id,
                asset_id=command.asset_id,
                listing_id=command.listing_id,
                provider=command.provider,
                external_id=command.external_id,
                created_at=command.created_at,
            )
        )
        await self.repository.flush()
        persisted = await self.repository.reload_alias(expected_id)
        if not _created_row_matches(persisted, command, expected_id):
            raise AssetAliasStateError()
        assert isinstance(persisted, AssetAliasModel)
        _audit_alias(self.repository, command, persisted, replayed=False)
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
            asset, listing, aliases, external_alias, id_alias = await _load_state(
                self.read_repository,
                canonical,
            )
            await _reject_direct_identity_collision(self.read_repository, canonical)
            _assess_existing_state(
                command=canonical,
                asset=asset,
                listing=listing,
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

    async def health_summary(self, provider: AssetAliasProvider) -> dict[str, object]:
        if not isinstance(provider, AssetAliasProvider):
            raise AssetAliasInvalidError()
        provider_asset_types(provider)
        if self.session.in_transaction():
            raise AssetAliasStateError()
        as_of = datetime.now(UTC).replace(tzinfo=None)
        async with self.session.begin():
            await self.repository.set_transaction_read_only()
            result = await self.repository.health_summary(provider, as_of=as_of)
        if self.session.in_transaction():
            await self.session.rollback()
            raise AssetAliasStateError()
        return result


class AssetAliasDecisionService:
    """Record an explicit rejection without changing any identity mapping."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _WriterRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or AssetAliasWriterRepository(session)

    async def reject(self, command: RejectAssetAliasCommand) -> RejectAssetAliasResult:
        canonical = validate_reject_asset_alias_command(command)
        if self.session.in_transaction():
            raise AssetAliasStateError()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    await self.repository.set_transaction_serializable()
                    await self.repository.acquire_identity_locks(
                        tuple(
                            sorted(
                                (
                                    asset_provider_lock_scope(
                                        canonical.asset_id, canonical.provider
                                    ),
                                    provider_external_lock_scope(
                                        canonical.provider, canonical.external_id
                                    ),
                                )
                            )
                        )
                    )
                    asset = await self.repository.load_asset(canonical.asset_id)
                    listing = await self.repository.load_listing(canonical.listing_id)
                    if asset is None or listing is None:
                        raise AssetAliasNotFoundError()
                    if listing.asset_id != asset.id or asset.asset_type not in provider_asset_types(
                        canonical.provider
                    ):
                        raise AssetAliasConflictError()
                    existing = await self.repository.load_provider_external_alias(
                        canonical.provider, canonical.external_id
                    )
                    direct = await self.repository.load_provider_listings(
                        PriceSource(canonical.provider.value), canonical.external_id
                    )
                    if existing is not None or direct:
                        raise AssetAliasConflictError()
                    self.repository.add_audit(
                        AssetAliasAuditModel(
                            id=str(uuid4()),
                            actor=canonical.actor,
                            action="rejected",
                            asset_id=canonical.asset_id,
                            listing_id=canonical.listing_id,
                            provider=canonical.provider.value,
                            external_id=canonical.external_id,
                            before_identity=None,
                            after_identity=None,
                            reason=canonical.reason,
                        )
                    )
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
            return RejectAssetAliasResult(
                asset_id=canonical.asset_id,
                listing_id=canonical.listing_id,
                provider=canonical.provider,
                external_id=canonical.external_id,
            )
        raise AssetAliasDatabaseUnavailableError()


class AssetListingCreationService:
    """Create a direct provider listing only from an explicit operator command."""

    def __init__(
        self, session: AsyncSession, *, repository: _WriterRepository | None = None
    ) -> None:
        self.session = session
        self.repository = repository or AssetAliasWriterRepository(session)

    async def create(self, command: CreateAssetListingCommand) -> CreateAssetListingResult:
        canonical = validate_create_asset_listing_command(command)
        if self.session.in_transaction():
            raise AssetAliasStateError()
        listing_id = str(
            uuid5(
                ASSET_ALIAS_NAMESPACE,
                "listing\0"
                + "\0".join(
                    (
                        canonical.asset_id,
                        canonical.symbol,
                        canonical.exchange,
                        canonical.currency,
                    )
                ),
            )
        )
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    await self.repository.set_transaction_serializable()
                    await self.repository.acquire_identity_locks(
                        tuple(
                            sorted(
                                (
                                    asset_provider_lock_scope(
                                        canonical.asset_id, canonical.provider
                                    ),
                                    provider_external_lock_scope(
                                        canonical.provider, canonical.provider_symbol
                                    ),
                                )
                            )
                        )
                    )
                    asset = await self.repository.load_asset(canonical.asset_id)
                    if asset is None:
                        raise AssetAliasNotFoundError()
                    if (
                        asset.symbol != canonical.expected_symbol
                        or asset.asset_type is not canonical.expected_asset_type
                        or asset.currency != canonical.expected_currency
                        or (
                            canonical.expected_isin is not None
                            and asset.isin != canonical.expected_isin
                        )
                    ):
                        raise AssetAliasConflictError()
                    existing = await self.repository.load_listing(listing_id)
                    provider_listings = await self.repository.load_provider_listings(
                        PriceSource(canonical.provider.value), canonical.provider_symbol
                    )
                    provider_alias = await self.repository.load_provider_external_alias(
                        canonical.provider, canonical.provider_symbol
                    )
                    if provider_alias is not None:
                        raise AssetAliasConflictError()
                    if existing is None:
                        if provider_listings:
                            raise AssetAliasConflictError()
                        existing = AssetListingModel(
                            id=listing_id,
                            asset_id=canonical.asset_id,
                            symbol=canonical.symbol,
                            exchange=canonical.exchange,
                            mic=canonical.mic,
                            currency=canonical.currency,
                            country=None,
                            provider=PriceSource(canonical.provider.value),
                            provider_symbol=canonical.provider_symbol,
                            is_primary=False,
                            base_priority=canonical.base_priority,
                            created_at=canonical.created_at,
                            updated_at=canonical.created_at,
                        )
                        self.repository.add_listing(existing)
                        await self.repository.flush()
                        persisted = await self.repository.load_listing(listing_id)
                        if persisted is None:
                            raise AssetAliasStateError()
                        existing = persisted
                        action = "listing_created"
                    else:
                        action = "listing_replayed"
                    if (
                        existing.asset_id != canonical.asset_id
                        or existing.symbol != canonical.symbol
                        or existing.exchange != canonical.exchange
                        or existing.mic != canonical.mic
                        or existing.currency != canonical.currency
                        or existing.provider is not PriceSource(canonical.provider.value)
                        or existing.provider_symbol != canonical.provider_symbol
                        or existing.base_priority != canonical.base_priority
                        or existing.is_primary is not False
                        or len(provider_listings) > 1
                        or (provider_listings and provider_listings[0].id != listing_id)
                    ):
                        raise AssetAliasConflictError()
                    identity = {
                        "listingId": listing_id,
                        "assetId": canonical.asset_id,
                        "symbol": canonical.symbol,
                        "exchange": canonical.exchange,
                        "mic": canonical.mic,
                        "currency": canonical.currency,
                        "provider": canonical.provider.value,
                        "providerSymbol": canonical.provider_symbol,
                        "basePriority": canonical.base_priority,
                    }
                    self.repository.add_audit(
                        AssetAliasAuditModel(
                            id=str(uuid4()),
                            actor=canonical.actor,
                            action=action,
                            asset_id=canonical.asset_id,
                            listing_id=listing_id,
                            provider=canonical.provider.value,
                            external_id=canonical.provider_symbol,
                            before_identity=identity if action == "listing_replayed" else None,
                            after_identity=identity,
                            reason=None,
                        )
                    )
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
            return CreateAssetListingResult(
                listing_id=listing_id,
                asset_id=canonical.asset_id,
                provider=canonical.provider,
                provider_symbol=canonical.provider_symbol,
                disposition="created" if action == "listing_created" else "replayed",
            )
        raise AssetAliasDatabaseUnavailableError()


__all__ = [
    "ASSET_ALIAS_NAMESPACE",
    "AssetAliasDecisionService",
    "AssetAliasInventoryService",
    "AssetAliasOnboardingService",
    "AssetAliasWriter",
    "AssetListingCreationService",
    "asset_alias_id",
]
