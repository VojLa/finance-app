from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import (
    AssetAliasProvider,
    AssetType,
    ImportSource,
    PriceSource,
)
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasOnboardingDisposition,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
)
from app.modules.imports.anycoin_btc_alias import (
    AnycoinBtcAliasService,
    OnboardAnycoinBtcAliasCommand,
    OnboardAnycoinBtcAliasResult,
    _PostedAssetMovement,
)
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)

CREATED_AT = datetime(2026, 8, 19, 10, 30, 0, 123000)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True

    async def __aexit__(self, *_: object) -> None:
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _rollback(self) -> None:
        self.active = False

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _Repository:
    def __init__(self, movements: tuple[_PostedAssetMovement, ...]) -> None:
        self.movements = movements
        self.read_only_calls = 0
        self.list_calls = 0

    async def set_transaction_read_only(self) -> None:
        self.read_only_calls += 1

    async def list_posted_asset_movements(self, **_: object) -> tuple[_PostedAssetMovement, ...]:
        self.list_calls += 1
        return self.movements


class _Writer:
    def __init__(self) -> None:
        self.commands: list[OnboardAssetAliasCommand] = []
        self._lock = asyncio.Lock()

    async def write(self, command: OnboardAssetAliasCommand) -> OnboardAssetAliasResult:
        async with self._lock:
            self.commands.append(command)
            return OnboardAssetAliasResult(
                alias_id="alias-btc",
                asset_id=command.asset_id,
                provider=command.provider,
                external_id=command.external_id,
                disposition=(
                    AssetAliasOnboardingDisposition.created
                    if len(self.commands) == 1
                    else AssetAliasOnboardingDisposition.replayed
                ),
            )


def _command(source: ImportSource = ImportSource.anycoin) -> OnboardAnycoinBtcAliasCommand:
    return OnboardAnycoinBtcAliasCommand(
        account_id="account-a",
        batch_ids=("batch-a",),
        source=source,
        created_at=CREATED_AT,
    )


def _movement(
    *,
    symbol: str = "BTC",
    asset_id: str | None = "asset-btc",
    listing_id: str | None = "listing-btc",
    asset_type: AssetType | None = AssetType.crypto,
) -> _PostedAssetMovement:
    return _PostedAssetMovement(
        movement_id=f"movement-{asset_id}-{listing_id}",
        source_symbol=symbol,
        source_asset_type=asset_type,
        asset_id=asset_id,
        listing_id=listing_id,
        asset_symbol=None if asset_id is None else symbol,
        asset_type=None if asset_id is None else asset_type,
        asset_currency=None if asset_id is None else symbol,
        asset_isin=None,
        listing_asset_id=None if listing_id is None else asset_id,
        listing_symbol=None if listing_id is None else symbol,
        listing_provider=None if listing_id is None else PriceSource.exchange,
        listing_provider_symbol=None if listing_id is None else symbol,
        listing_exchange=None if listing_id is None else "anycoin",
        listing_currency=None if listing_id is None else "EUR",
    )


async def test_exact_anycoin_btc_allowlist_writes_once_and_replay_is_idempotent() -> None:
    repository = _Repository((_movement(), _movement()))
    writer = _Writer()
    session = _Session()
    service = AnycoinBtcAliasService(
        session,  # type: ignore[arg-type]
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=repository,
        writer=writer,
    )

    created = await service.onboard(_command())
    replayed = await service.onboard(_command())

    assert [result.disposition for result in (*created.aliases, *replayed.aliases)] == [
        AssetAliasOnboardingDisposition.created,
        AssetAliasOnboardingDisposition.replayed,
    ]
    assert len(writer.commands) == 2
    assert all(command.external_id == "bitcoin" for command in writer.commands)
    assert all(command.provider is AssetAliasProvider.coingecko for command in writer.commands)
    assert all(command.expected_symbol == "BTC" for command in writer.commands)
    assert repository.read_only_calls == repository.list_calls == 2


@pytest.mark.parametrize("symbol", ["ETH", "WBTC", "btc", " BTC "])
async def test_non_allowlisted_symbols_never_write(symbol: str) -> None:
    repository = _Repository((_movement(symbol=symbol),))
    writer = _Writer()
    session = _Session()
    result = await AnycoinBtcAliasService(
        session,  # type: ignore[arg-type]
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=repository,
        writer=writer,
    ).onboard(_command())

    assert result.aliases == ()
    assert writer.commands == []


async def test_non_anycoin_source_never_reads_or_writes() -> None:
    repository = _Repository((_movement(),))
    writer = _Writer()
    session = _Session()
    result = await AnycoinBtcAliasService(
        session,  # type: ignore[arg-type]
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=repository,
        writer=writer,
    ).onboard(_command(ImportSource.trading212))

    assert result.aliases == ()
    assert repository.list_calls == 0
    assert writer.commands == []


@pytest.mark.parametrize(
    "movement",
    [
        _movement(asset_id=None),
        _movement(listing_id=None),
        _movement(asset_type=AssetType.other),
    ],
)
async def test_btc_without_one_exact_canonical_identity_fails_before_writer(
    movement: _PostedAssetMovement,
) -> None:
    writer = _Writer()
    session = _Session()
    service = AnycoinBtcAliasService(
        session,  # type: ignore[arg-type]
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=_Repository((movement,)),
        writer=writer,
    )

    with pytest.raises(AssetAliasConflictError):
        await service.onboard(_command())

    assert writer.commands == []


async def test_multiple_btc_assets_fail_before_writer() -> None:
    writer = _Writer()
    session = _Session()
    service = AnycoinBtcAliasService(
        session,  # type: ignore[arg-type]
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=_Repository(
            (
                _movement(asset_id="asset-a", listing_id="listing-a"),
                _movement(asset_id="asset-b", listing_id="listing-b"),
            )
        ),
        writer=writer,
    )

    with pytest.raises(AssetAliasConflictError):
        await service.onboard(_command())

    assert writer.commands == []


async def test_concurrent_service_calls_delegate_to_writer_identity_lock_boundary() -> None:
    writer = _Writer()

    async def run() -> OnboardAnycoinBtcAliasResult:
        session = _Session()
        return await AnycoinBtcAliasService(
            session,  # type: ignore[arg-type]
            source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
            repository=_Repository((_movement(),)),
            writer=writer,
        ).onboard(_command())

    first, second = await asyncio.gather(run(), run())

    assert {
        first.aliases[0].disposition,
        second.aliases[0].disposition,
    } == {
        AssetAliasOnboardingDisposition.created,
        AssetAliasOnboardingDisposition.replayed,
    }
    assert len(writer.commands) == 2


async def test_local_free_anycoin_btc_uses_asset_wide_coingecko_identity() -> None:
    writer = _Writer()
    result = await AnycoinBtcAliasService(
        _Session(),  # type: ignore[arg-type]
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=_Repository((_movement(),)),
        writer=writer,
    ).onboard(_command())

    assert len(result.aliases) == 1
    assert writer.commands == [
        OnboardAssetAliasCommand(
            actor="system:anycoin-import",
            asset_id="asset-btc",
            listing_id=None,
            provider=AssetAliasProvider.coingecko,
            external_id="bitcoin",
            expected_symbol="BTC",
            expected_asset_type=AssetType.crypto,
            expected_currency="BTC",
            expected_isin=None,
            created_at=CREATED_AT,
        )
    ]
