from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import (
    AssetAliasProvider,
    AssetType,
    ImportSource,
    PriceSource,
)
from app.modules.asset_aliases.identity import canonical_external_id
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasOnboardingDisposition,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
)
from app.modules.imports.trading212_asset_alias import (
    OnboardTrading212AssetAliasesCommand,
    Trading212AssetAliasService,
    _PostedAsset,
)
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)

CREATED_AT = datetime(2026, 9, 4, 12, 0, 0, 123000)


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
    def __init__(self, rows: tuple[_PostedAsset, ...]) -> None:
        self.rows = rows
        self.read_only_calls = 0
        self.list_calls = 0

    async def set_transaction_read_only(self) -> None:
        self.read_only_calls += 1

    async def list_posted_assets(self, **_: object) -> tuple[_PostedAsset, ...]:
        self.list_calls += 1
        return self.rows


class _Writer:
    def __init__(self) -> None:
        self.commands: list[OnboardAssetAliasCommand] = []

    async def write(self, command: OnboardAssetAliasCommand) -> OnboardAssetAliasResult:
        self.commands.append(command)
        return OnboardAssetAliasResult(
            alias_id=f"alias-{command.asset_id}",
            asset_id=command.asset_id,
            provider=command.provider,
            external_id=command.external_id,
            disposition=AssetAliasOnboardingDisposition.created,
        )


def _command(
    source: ImportSource = ImportSource.trading212,
) -> OnboardTrading212AssetAliasesCommand:
    return OnboardTrading212AssetAliasesCommand(
        account_id="account-a",
        batch_ids=("batch-a",),
        source=source,
        created_at=CREATED_AT,
    )


def _row(
    *,
    symbol: str = "VUAA",
    isin: str = "IE00BFMXXD54",
    currency: str = "EUR",
    asset_id: str = "asset-vuaa",
) -> _PostedAsset:
    return _PostedAsset(
        movement_id=f"movement-{asset_id}",
        source_symbol=symbol,
        source_asset_type=AssetType.other,
        asset_id=asset_id,
        asset_symbol=symbol,
        asset_type=AssetType.other,
        asset_currency=currency,
        asset_isin=isin,
        listing_id=f"listing-{asset_id}",
        listing_asset_id=asset_id,
        listing_symbol=symbol,
        listing_provider=PriceSource.broker,
        listing_provider_symbol=symbol,
        listing_exchange=ImportSource.trading212.value,
        listing_currency=currency,
    )


async def _run(
    row: _PostedAsset,
    *,
    canonical: bool = False,
) -> tuple[_Repository, _Writer]:
    repository = _Repository((row, row))
    writer = _Writer()
    await Trading212AssetAliasService(
        _Session(),  # type: ignore[arg-type]
        source_policy=(
            CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
            if canonical
            else LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
        ),
        repository=repository,
        writer=writer,
    ).onboard(_command())
    return repository, writer


async def test_local_free_vuaa_uses_accepted_milan_yahoo_identity_once() -> None:
    repository, writer = await _run(_row())

    assert repository.read_only_calls == repository.list_calls == 1
    assert writer.commands == [
        OnboardAssetAliasCommand(
            actor="system:trading212-import",
            asset_id="asset-vuaa",
            listing_id="listing-asset-vuaa",
            provider=AssetAliasProvider.yahoo_finance,
            external_id="VUAA.MI",
            expected_symbol="VUAA",
            expected_asset_type=AssetType.other,
            expected_currency="EUR",
            expected_isin="IE00BFMXXD54",
            created_at=CREATED_AT,
        )
    ]


async def test_local_free_bb3m_keeps_exact_usd_london_listing() -> None:
    _, writer = await _run(
        _row(
            symbol="BB3M",
            isin="IE00BMD8KM66",
            currency="USD",
            asset_id="asset-bb3m",
        )
    )

    assert writer.commands[0].external_id == "BB3M.L"
    assert writer.commands[0].expected_currency == "USD"


async def test_canonical_vuaa_uses_twelve_data_milan_identity() -> None:
    _, writer = await _run(_row(), canonical=True)

    assert writer.commands[0].provider is AssetAliasProvider.twelve_data
    assert writer.commands[0].external_id == canonical_external_id(
        AssetAliasProvider.twelve_data,
        '{"symbol":"VUAA","mic_code":"XMIL"}',
    )


async def test_unknown_identity_fails_closed_before_write() -> None:
    writer = _Writer()
    service = Trading212AssetAliasService(
        _Session(),  # type: ignore[arg-type]
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=_Repository((_row(symbol="UNKNOWN"),)),
        writer=writer,
    )

    with pytest.raises(AssetAliasConflictError):
        await service.onboard(_command())

    assert writer.commands == []


async def test_non_trading_source_does_not_read_or_write() -> None:
    repository = _Repository((_row(),))
    writer = _Writer()
    result = await Trading212AssetAliasService(
        _Session(),  # type: ignore[arg-type]
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        repository=repository,
        writer=writer,
    ).onboard(_command(ImportSource.anycoin))

    assert result.aliases == ()
    assert repository.list_calls == 0
    assert writer.commands == []
