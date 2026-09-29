from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.assets import AssetAliasModel
from app.db.models.enums import (
    AssetAliasProvider,
    ImportSource,
)
from app.db.models.ledger import InvestmentMovementModel
from app.main import create_app
from app.modules.asset_aliases.models import AssetAliasOnboardingDisposition
from app.modules.imports.anycoin_btc_alias import (
    AnycoinBtcAliasService,
    OnboardAnycoinBtcAliasCommand,
)
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    ImportMultiFileFinalizationService,
)
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
)
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    market_evidence_source_policy_from_settings,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from tests.support import investment_fixture_e2e as investment_support

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=investment_support.SECRET,
        twelve_data_api_key="anycoin-btc-alias-test-key",
        _env_file=None,
    )


class _CoinGeckoHarness:
    def __init__(self, observed_at: datetime) -> None:
        self.observed_at = observed_at
        self.calls: list[str] = []

    def transport(self, session: AsyncSession) -> httpx.MockTransport:
        epoch = int(self.observed_at.replace(tzinfo=UTC).timestamp())

        def handler(request: httpx.Request) -> httpx.Response:
            assert not session.in_transaction()
            coin_id = request.url.params["ids"]
            self.calls.append(coin_id)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    coin_id: {
                        "eur": 50000.0,
                        "last_updated_at": epoch,
                    }
                },
            )

        return httpx.MockTransport(handler)


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name="Anycoin alias test owner",
    )


def _run_anycoin_stages(
    client: TestClient,
    *,
    user_id: str,
    account_id: str,
    content: bytes,
) -> str:
    created = client.post(
        f"/api/v1/accounts/{account_id}/imports",
        headers=investment_support.headers(user_id),
        json={
            "source": ImportSource.anycoin.value,
            "filename": "history.csv",
            "file_size": len(content),
            "file_encoding": None,
            "checksum": hashlib.sha256(content).hexdigest(),
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "upload_required"
    batch_id = body["batch"]["id"]
    base = f"/api/v1/accounts/{account_id}/imports/{batch_id}"
    uploaded = client.put(
        f"{base}/file",
        headers=investment_support.headers(user_id, binary=True),
        content=content,
    )
    assert uploaded.status_code == 200, uploaded.text
    for stage in ("parse", "normalize", "deduplicate", "classify"):
        response = client.post(
            f"{base}/{stage}",
            headers=investment_support.headers(user_id),
        )
        assert response.status_code == 200, response.text
    return batch_id


async def _finalize(
    *,
    user_id: str,
    account_id: str,
    batch_id: str,
    harness: _CoinGeckoHarness,
):
    engine = investment_support.engine()
    try:
        async with AsyncSession(engine) as session:
            coin = harness.transport(session)

            def market_factory(active_session: AsyncSession, settings: Settings):
                return create_production_market_evidence_service(
                    active_session,
                    settings,
                    coingecko_http_transport=coin,
                )

            market = MarketBackedSnapshotRefreshService(
                session,
                _settings(),
                market_service_factory=market_factory,
            )
            return await ImportMultiFileFinalizationService(
                session,
                market_backed_service=market,
                source_policy=market_evidence_source_policy_from_settings(_settings()),
            ).finalize(
                FinalizeImportBatchesCommand(
                    principal=_principal(user_id),
                    account_id=account_id,
                    batch_ids=(batch_id,),
                )
            )
    finally:
        await engine.dispose()


async def _alias_rows(account_id: str) -> tuple[AssetAliasModel, ...]:
    engine = investment_support.engine()
    try:
        async with AsyncSession(engine) as session:
            rows = tuple(
                await session.scalars(
                    select(AssetAliasModel)
                    .join(
                        InvestmentMovementModel,
                        InvestmentMovementModel.asset_id == AssetAliasModel.asset_id,
                    )
                    .where(InvestmentMovementModel.account_id == account_id)
                    .order_by(AssetAliasModel.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows
    finally:
        await engine.dispose()


def test_real_anycoin_finalization_onboards_btc_before_mocked_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"anycoin-btc-auto-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(
        investment_support.seed_identity(prefix, source=ImportSource.anycoin)
    )
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / prefix))
    app = create_app(_settings())
    observed_at = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0) - timedelta(
        minutes=1
    )
    harness = _CoinGeckoHarness(observed_at)
    try:
        with TestClient(app) as client:
            batch_id = _run_anycoin_stages(
                client,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(ImportSource.anycoin, "history.csv"),
            )
        asyncio.run(
            _post_only(
                user_id=user_id,
                account_id=account_id,
                batch_id=batch_id,
            )
        )

        first = asyncio.run(
            _finalize(
                user_id=user_id,
                account_id=account_id,
                batch_id=batch_id,
                harness=harness,
            )
        )
        second = asyncio.run(
            _finalize(
                user_id=user_id,
                account_id=account_id,
                batch_id=batch_id,
                harness=harness,
            )
        )
        aliases = asyncio.run(_alias_rows(account_id))

        assert first.snapshot_refresh_status.value == "created"
        assert second.snapshot_refresh_status.value == "replayed"
        assert len(aliases) == 1
        assert aliases[0].provider is AssetAliasProvider.coingecko
        assert aliases[0].external_id == "bitcoin"
        assert harness.calls == ["bitcoin", "bitcoin"]
    finally:
        asyncio.run(investment_support.cleanup(prefix))


async def _post_only(*, user_id: str, account_id: str, batch_id: str) -> datetime:
    engine = investment_support.engine()
    try:
        async with AsyncSession(engine) as session:
            result = await ImportBatchPostingService(session).post_batch(
                PostImportBatchCommand(
                    principal=_principal(user_id),
                    account_id=account_id,
                    batch_id=batch_id,
                )
            )
            return result.completed_at
    finally:
        await engine.dispose()


async def _concurrent_onboard(
    *,
    account_id: str,
    batch_id: str,
    completed_at: datetime,
) -> object:
    engine = investment_support.engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            return await AnycoinBtcAliasService(
                session,
                source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
            ).onboard(
                OnboardAnycoinBtcAliasCommand(
                    account_id=account_id,
                    batch_ids=(batch_id,),
                    source=ImportSource.anycoin,
                    created_at=completed_at,
                )
            )
    finally:
        await engine.dispose()


def test_concurrent_anycoin_alias_onboarding_converges_to_one_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"anycoin-btc-concurrent-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(
        investment_support.seed_identity(prefix, source=ImportSource.anycoin)
    )
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / prefix))
    app = create_app(_settings())
    try:
        with TestClient(app) as client:
            batch_id = _run_anycoin_stages(
                client,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(ImportSource.anycoin, "history.csv"),
            )
        completed_at = asyncio.run(
            _post_only(
                user_id=user_id,
                account_id=account_id,
                batch_id=batch_id,
            )
        )

        async def run() -> tuple[object, object]:
            return await asyncio.gather(
                _concurrent_onboard(
                    account_id=account_id,
                    batch_id=batch_id,
                    completed_at=completed_at,
                ),
                _concurrent_onboard(
                    account_id=account_id,
                    batch_id=batch_id,
                    completed_at=completed_at,
                ),
            )

        first, second = asyncio.run(run())
        dispositions = {
            first.aliases[0].disposition,  # type: ignore[attr-defined]
            second.aliases[0].disposition,  # type: ignore[attr-defined]
        }

        assert dispositions == {
            AssetAliasOnboardingDisposition.created,
            AssetAliasOnboardingDisposition.replayed,
        }
        assert len(asyncio.run(_alias_rows(account_id))) == 1
    finally:
        asyncio.run(investment_support.cleanup(prefix))
