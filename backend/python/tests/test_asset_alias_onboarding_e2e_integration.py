"""Clean-database recovery through staged imports and the actual operator CLI."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_db_session
from app.db.models.enums import ImportSource
from app.main import create_app
from app.modules.imports.api import (
    get_import_market_backed_snapshot_refresh_service,
)
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.snapshot_refresh.api import (
    get_market_backed_snapshot_refresh_service,
    get_user_snapshot_refresh_clock,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)
PYTHON_ROOT = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")

investment_support = cast(
    Any,
    importlib.import_module("tests.support.investment_fixture_e2e"),
)
refresh_support = cast(
    Any,
    importlib.import_module("tests.test_import_market_backed_refresh_integration"),
)


def _cli(
    arguments: list[str],
    *,
    database_url: str | None = DATABASE_URL,
) -> subprocess.CompletedProcess[str]:
    assert UV is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url or ""
    return subprocess.run(
        [UV, "run", "python", "scripts/asset_alias.py", *arguments],
        cwd=PYTHON_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _onboard_arguments(
    item: dict[str, Any],
    *,
    provider: str,
    external_id: str,
) -> list[str]:
    arguments = [
        "onboard",
        "--asset-id",
        item["assetId"],
        "--expected-symbol",
        item["symbol"],
        "--expected-asset-type",
        item["assetType"],
        "--expected-currency",
        item["currency"],
        "--provider",
        provider,
        "--external-id",
        external_id,
    ]
    if item["isin"] is not None:
        arguments.extend(("--expected-isin", item["isin"]))
    return arguments


def _install_market_overrides(
    app: Any,
    harness: Any,
    *,
    manual_bucket: datetime,
) -> None:
    def service(
        session: AsyncSession = Depends(get_db_session),
    ) -> MarketBackedSnapshotRefreshService:
        twelve, coingecko, cnb = harness.transports(session)

        def factory(active_session: AsyncSession, settings: Any):
            return create_production_market_evidence_service(
                active_session,
                settings,
                http_transport=cnb,
                coingecko_http_transport=coingecko,
                twelve_data_http_transport=twelve,
            )

        return MarketBackedSnapshotRefreshService(
            session,
            refresh_support._settings(),
            market_service_factory=factory,
        )

    app.dependency_overrides[get_import_market_backed_snapshot_refresh_service] = service
    app.dependency_overrides[get_market_backed_snapshot_refresh_service] = service
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: manual_bucket


@pytest.mark.parametrize(
    (
        "source",
        "fixture_name",
        "provider",
        "external_id",
        "expected_call",
    ),
    [
        (
            ImportSource.trading212,
            "activity.csv",
            "twelve_data",
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            ("twelve_data", "AAPL:XNAS"),
        ),
        (
            ImportSource.anycoin,
            "history.csv",
            "coingecko",
            "bitcoin",
            ("coingecko", "bitcoin"),
        ),
    ],
)
def test_clean_import_and_manual_recovery_use_actual_cli_without_direct_insert(
    source: ImportSource,
    fixture_name: str,
    provider: str,
    external_id: str,
    expected_call: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    prefix = f"r5b4-recovery-{source.value}-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(investment_support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    observed_at = refresh_support._observed_at()
    harness = refresh_support._ProviderHarness(observed_at=observed_at)
    app = create_app(refresh_support._settings())
    manual_bucket = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0) + timedelta(
        minutes=2
    )
    _install_market_overrides(app, harness, manual_bucket=manual_bucket)
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(source, fixture_name),
                filename=fixture_name,
                post=False,
            )
            asyncio.run(investment_support.seed_asset_listing(prefix, source=source))
            if source is ImportSource.trading212:
                asyncio.run(refresh_support._configure_trading_czk(prefix))

            unavailable = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            assert unavailable["snapshot_refresh_status"] == "unavailable"
            assert harness.calls == []

            before = asyncio.run(refresh_support._database_state(prefix))
            assert len(before["holdings"]) == 1
            assert before["prices"] == ()
            assert before["snapshots"] == ()
            assert before["net_worth"] == ()

            inventory_process = _cli(["list-unresolved", "--provider", provider])
            assert inventory_process.returncode == 0
            assert inventory_process.stderr == ""
            inventory = json.loads(inventory_process.stdout)
            assert inventory == sorted(
                inventory,
                key=lambda item: (item["symbol"], item["assetId"]),
            )
            item = next(value for value in inventory if value["assetId"] == f"{prefix}-asset")
            assert item["listings"] == [
                {
                    "currency": "EUR",
                    "exchange": source.value,
                    "listingId": f"{prefix}-listing",
                    "provider": ("broker" if source is ImportSource.trading212 else "exchange"),
                    "providerSymbol": item["symbol"],
                }
            ]

            onboard_arguments = _onboard_arguments(
                item,
                provider=provider,
                external_id=external_id,
            )
            dry_run = _cli([*onboard_arguments, "--dry-run"])
            assert dry_run.returncode == 0
            assert dry_run.stderr == ""
            assert json.loads(dry_run.stdout)["disposition"] == "dry_run"

            created = _cli(onboard_arguments)
            assert created.returncode == 0
            assert created.stderr == ""
            created_document = json.loads(created.stdout)
            assert created_document["disposition"] == "created"
            assert created_document["externalId"] == external_id

            replayed = _cli(onboard_arguments)
            assert replayed.returncode == 0
            assert replayed.stderr == ""
            replayed_document = json.loads(replayed.stdout)
            assert replayed_document["disposition"] == "replayed"
            assert replayed_document["aliasId"] == created_document["aliasId"]

            conflict = _cli(
                _onboard_arguments(
                    item,
                    provider=provider,
                    external_id=(
                        "ethereum"
                        if provider == "coingecko"
                        else '{"symbol":"MSFT","mic_code":"XNAS"}'
                    ),
                )
            )
            assert conflict.returncode == 4
            assert conflict.stdout == ""
            assert json.loads(conflict.stderr) == {"error": {"code": "asset_alias_conflict"}}

            invalid = _cli(
                _onboard_arguments(
                    item,
                    provider=provider,
                    external_id=(
                        "bitcoin,ethereum"
                        if provider == "coingecko"
                        else '{"mic_code":"XNAS","symbol":"AAPL"}'
                    ),
                )
            )
            assert invalid.returncode == 2
            assert invalid.stdout == ""
            assert json.loads(invalid.stderr) == {"error": {"code": "asset_alias_invalid"}}

            recovered = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            replay = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            manual = client.post(
                "/api/v1/snapshot-refresh/recalculate",
                headers=investment_support.headers(user_id),
            )

        assert recovered["snapshot_refresh_status"] == "created"
        assert replay["snapshot_refresh_status"] == "replayed"
        assert manual.status_code == 200, manual.text
        assert expected_call in harness.calls
        if provider == "twelve_data":
            assert not any(name == "coingecko" for name, _ in harness.calls)
        else:
            assert not any(name in {"twelve_data", "cnb"} for name, _ in harness.calls)

        after = asyncio.run(refresh_support._database_state(prefix))
        assert len(after["holdings"]) == len(after["prices"]) == 1
        assert len(after["snapshots"]) >= 1
        assert len(after["net_worth"]) >= 1
        refresh_support._assert_read_parity(
            app,
            headers=investment_support.headers(user_id),
            account_id=account_id,
            state=after,
        )
        assert DATABASE_URL not in (
            inventory_process.stdout
            + created.stdout
            + replayed.stdout
            + conflict.stderr
            + invalid.stderr
        )
    finally:
        asyncio.run(refresh_support._cleanup(prefix))
        asyncio.run(refresh_support._delete_cnb_rates())


def test_actual_cli_missing_database_url_is_safe_json() -> None:
    process = _cli(
        ["list-unresolved", "--provider", "coingecko"],
        database_url="",
    )

    assert process.returncode == 6
    assert process.stdout == ""
    assert "Traceback" not in process.stderr
    assert "postgresql://" not in process.stderr
    assert json.loads(process.stderr) == {"error": {"code": "asset_alias_database_unavailable"}}
