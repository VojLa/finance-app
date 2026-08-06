from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, cast

import pytest

from app.db.models.assets import AssetAliasModel, AssetModel
from app.db.models.enums import AssetAliasProvider, AssetType
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasInvalidError,
    AssetAliasNotFoundError,
    AssetAliasOnboardingDisposition,
    AssetAliasStateError,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
)
from app.modules.asset_aliases.service import (
    AssetAliasOnboardingService,
    AssetAliasWriter,
    asset_alias_id,
)

CREATED_AT = datetime(2026, 8, 5, 12, 30, 0, 123000)


def _command(**overrides: object) -> OnboardAssetAliasCommand:
    values: dict[str, object] = {
        "asset_id": "asset-a",
        "provider": AssetAliasProvider.coingecko,
        "external_id": "bitcoin",
        "expected_symbol": "BTC",
        "expected_asset_type": AssetType.crypto,
        "expected_currency": "EUR",
        "expected_isin": None,
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return OnboardAssetAliasCommand(**values)  # type: ignore[arg-type]


def _asset(**overrides: object) -> AssetModel:
    values: dict[str, object] = {
        "id": "asset-a",
        "symbol": "BTC",
        "asset_type": AssetType.crypto,
        "currency": "EUR",
        "isin": None,
        "name": "Bitcoin",
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }
    values.update(overrides)
    return AssetModel(**values)


def _alias(**overrides: object) -> AssetAliasModel:
    values: dict[str, object] = {
        "id": "historical-alias-id",
        "asset_id": "asset-a",
        "provider": AssetAliasProvider.coingecko,
        "external_id": "bitcoin",
        "created_at": datetime(2025, 1, 1),
    }
    values.update(overrides)
    return AssetAliasModel(**values)


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self.session.active = False


class _Session:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)

    async def rollback(self) -> None:
        self.active = False
        self.rollback_count += 1


class _Repository:
    def __init__(
        self,
        *,
        asset: AssetModel | None | object = ...,
        aliases: tuple[AssetAliasModel, ...] = (),
        external_alias: AssetAliasModel | None = None,
        id_alias: AssetAliasModel | None = None,
        reload_override: AssetAliasModel | None | object = ...,
    ) -> None:
        self.asset = _asset() if asset is ... else cast(AssetModel | None, asset)
        self.aliases = aliases
        self.external_alias = external_alias
        self.id_alias = id_alias
        self.reload_override = reload_override
        self.pending: AssetAliasModel | None = None
        self.read_only_count = 0
        self.serializable_count = 0
        self.lock_scopes: tuple[str, ...] = ()
        self.flush_count = 0

    async def set_transaction_read_only(self) -> None:
        self.read_only_count += 1

    async def set_transaction_serializable(self) -> None:
        self.serializable_count += 1

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None:
        self.lock_scopes = scopes

    async def load_asset(self, asset_id: str) -> AssetModel | None:
        return self.asset

    async def load_asset_provider_aliases(
        self,
        asset_id: str,
        provider: AssetAliasProvider,
    ) -> tuple[AssetAliasModel, ...]:
        return self.aliases

    async def load_provider_external_alias(
        self,
        provider: AssetAliasProvider,
        external_id: str,
    ) -> AssetAliasModel | None:
        return self.external_alias

    async def load_alias_by_id(self, alias_id: str) -> AssetAliasModel | None:
        return self.id_alias

    def add_alias(self, row: AssetAliasModel) -> None:
        self.pending = row

    async def flush(self) -> None:
        self.flush_count += 1

    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None:
        if self.reload_override is ...:
            return self.pending
        return cast(AssetAliasModel | None, self.reload_override)


class _Writer:
    def __init__(self, result: OnboardAssetAliasResult) -> None:
        self.result = result
        self.calls: list[OnboardAssetAliasCommand] = []

    async def write(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult:
        self.calls.append(command)
        return self.result


def _writer(
    repository: _Repository,
    *,
    active: bool = False,
) -> tuple[AssetAliasWriter, _Session]:
    session = _Session(active=active)
    return (
        AssetAliasWriter(
            cast(Any, session),
            repository=repository,
        ),
        session,
    )


@pytest.mark.asyncio
async def test_writer_creates_exact_immutable_alias() -> None:
    repository = _Repository()
    writer, session = _writer(repository)

    result = await writer.write(_command())

    expected_id = asset_alias_id("asset-a", AssetAliasProvider.coingecko)
    assert result == OnboardAssetAliasResult(
        alias_id=expected_id,
        asset_id="asset-a",
        provider=AssetAliasProvider.coingecko,
        external_id="bitcoin",
        disposition=AssetAliasOnboardingDisposition.created,
    )
    assert repository.pending is not None
    assert repository.pending.id == expected_id
    assert repository.pending.created_at == CREATED_AT
    assert repository.serializable_count == 1
    assert repository.lock_scopes == tuple(sorted(repository.lock_scopes))
    assert len(repository.lock_scopes) == 2
    assert repository.flush_count == 1
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_writer_replays_historical_exact_alias_without_mutation() -> None:
    existing = _alias()
    repository = _Repository(
        aliases=(existing,),
        external_alias=existing,
    )
    writer, _ = _writer(repository)

    result = await writer.write(_command(created_at=datetime(2026, 8, 5, 13)))

    assert result.alias_id == "historical-alias-id"
    assert result.disposition is AssetAliasOnboardingDisposition.replayed
    assert existing.created_at == datetime(2025, 1, 1)
    assert repository.pending is None
    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_writer_replays_exact_alias_when_all_identity_lookups_match() -> None:
    expected_id = asset_alias_id("asset-a", AssetAliasProvider.coingecko)
    existing = _alias(id=expected_id)
    repository = _Repository(
        aliases=(existing,),
        external_alias=_alias(id=expected_id),
        id_alias=_alias(id=expected_id),
    )
    writer, session = _writer(repository)

    result = await writer.write(_command(created_at=datetime(2026, 8, 5, 13)))

    assert result.alias_id == expected_id
    assert result.disposition is AssetAliasOnboardingDisposition.replayed
    assert repository.pending is None
    assert repository.flush_count == 0
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_historical_exact_replay_rejects_deterministic_id_collision() -> None:
    existing = _alias()
    collision = _alias(
        id=asset_alias_id("asset-a", AssetAliasProvider.coingecko),
        asset_id="asset-b",
        external_id="ethereum",
    )
    repository = _Repository(
        aliases=(existing,),
        external_alias=existing,
        id_alias=collision,
    )
    writer, session = _writer(repository)

    with pytest.raises(AssetAliasConflictError):
        await writer.write(_command())

    assert repository.pending is None
    assert repository.flush_count == 0
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_dry_run_rejects_historical_replay_deterministic_id_collision() -> None:
    existing = _alias()
    collision = _alias(
        id=asset_alias_id("asset-a", AssetAliasProvider.coingecko),
        asset_id="asset-b",
        external_id="ethereum",
    )
    repository = _Repository(
        aliases=(existing,),
        external_alias=existing,
        id_alias=collision,
    )
    session = _Session()
    fake_writer = _Writer(
        OnboardAssetAliasResult(
            alias_id="must-not-be-used",
            asset_id="asset-a",
            provider=AssetAliasProvider.coingecko,
            external_id="bitcoin",
            disposition=AssetAliasOnboardingDisposition.created,
        )
    )
    service = AssetAliasOnboardingService(
        cast(Any, session),
        read_repository=repository,
        writer=fake_writer,
    )

    with pytest.raises(AssetAliasConflictError):
        await service.onboard(_command(), dry_run=True)

    assert fake_writer.calls == []
    assert repository.pending is None
    assert repository.flush_count == 0
    assert not session.in_transaction()


@pytest.mark.parametrize(
    ("repository", "error"),
    [
        (
            _Repository(
                aliases=(_alias(),),
                external_alias=None,
            ),
            AssetAliasStateError,
        ),
        (
            _Repository(
                aliases=(_alias(),),
                external_alias=_alias(id="other-alias", asset_id="asset-b"),
            ),
            AssetAliasConflictError,
        ),
        (
            _Repository(
                aliases=(
                    _alias(
                        id=asset_alias_id(
                            "asset-a",
                            AssetAliasProvider.coingecko,
                        )
                    ),
                ),
                external_alias=_alias(
                    id=asset_alias_id(
                        "asset-a",
                        AssetAliasProvider.coingecko,
                    )
                ),
                id_alias=None,
            ),
            AssetAliasStateError,
        ),
        (
            _Repository(
                aliases=(_alias(),),
                external_alias=_alias(),
                id_alias=_alias(
                    id=asset_alias_id("asset-a", AssetAliasProvider.coingecko),
                    created_at=datetime(2025, 1, 1, microsecond=1),
                ),
            ),
            AssetAliasStateError,
        ),
    ],
)
@pytest.mark.asyncio
async def test_exact_replay_requires_coherent_lookup_state(
    repository: _Repository,
    error: type[Exception],
) -> None:
    writer, session = _writer(repository)

    with pytest.raises(error):
        await writer.write(_command())

    assert repository.pending is None
    assert repository.flush_count == 0
    assert not session.in_transaction()


@pytest.mark.parametrize(
    "repository,error",
    [
        (_Repository(asset=None), AssetAliasNotFoundError),
        (_Repository(asset=_asset(symbol="ETH")), AssetAliasConflictError),
        (_Repository(asset=_asset(asset_type=AssetType.stock)), AssetAliasConflictError),
        (_Repository(asset=_asset(currency="USD")), AssetAliasConflictError),
        (_Repository(asset=_asset(isin="OTHER")), AssetAliasConflictError),
        (
            _Repository(aliases=(_alias(external_id="ethereum"),)),
            AssetAliasConflictError,
        ),
        (
            _Repository(
                external_alias=_alias(asset_id="asset-b"),
            ),
            AssetAliasConflictError,
        ),
        (
            _Repository(
                aliases=(
                    _alias(id="alias-one"),
                    _alias(id="alias-two", external_id="ethereum"),
                )
            ),
            AssetAliasStateError,
        ),
        (
            _Repository(id_alias=_alias(asset_id="asset-b")),
            AssetAliasConflictError,
        ),
        (
            _Repository(reload_override=None),
            AssetAliasStateError,
        ),
    ],
)
@pytest.mark.asyncio
async def test_writer_fails_closed_without_update_or_delete(
    repository: _Repository,
    error: type[Exception],
) -> None:
    command = (
        _command(expected_isin="US0378331005")
        if repository.asset is not None and repository.asset.isin
        else _command()
    )
    writer, session = _writer(repository)

    with pytest.raises(error):
        await writer.write(command)

    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_writer_rejects_nonidle_session() -> None:
    writer, session = _writer(_Repository(), active=True)

    with pytest.raises(AssetAliasStateError):
        await writer.write(_command())

    assert session.in_transaction()


@pytest.mark.asyncio
async def test_service_dry_run_reads_target_but_never_calls_writer() -> None:
    session = _Session()
    repository = _Repository()
    fake_writer = _Writer(
        OnboardAssetAliasResult(
            alias_id="must-not-be-used",
            asset_id="asset-a",
            provider=AssetAliasProvider.coingecko,
            external_id="bitcoin",
            disposition=AssetAliasOnboardingDisposition.created,
        )
    )
    service = AssetAliasOnboardingService(
        cast(Any, session),
        read_repository=repository,
        writer=fake_writer,
    )

    result = await service.onboard(_command(), dry_run=True)

    assert result.alias_id is None
    assert result.disposition is AssetAliasOnboardingDisposition.dry_run
    assert fake_writer.calls == []
    assert repository.read_only_count == 1
    assert repository.serializable_count == 0
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_service_requires_boolean_dry_run_and_idle_session() -> None:
    session = _Session(active=True)
    service = AssetAliasOnboardingService(
        cast(Any, session),
        read_repository=_Repository(),
        writer=_Writer(
            OnboardAssetAliasResult(
                alias_id=None,
                asset_id="asset-a",
                provider=AssetAliasProvider.coingecko,
                external_id="bitcoin",
                disposition=AssetAliasOnboardingDisposition.dry_run,
            )
        ),
    )

    with pytest.raises(AssetAliasInvalidError):
        await service.onboard(_command(), dry_run=cast(Any, 1))
    with pytest.raises(AssetAliasStateError):
        await service.onboard(_command())
