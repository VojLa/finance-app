"""PostgreSQL bridge evidence from refresh manifest to exact 5L reads."""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole, AccountType
from app.main import create_app
from app.modules.snapshot_refresh.api import get_user_snapshot_refresh_clock

manual_support = cast(
    Any,
    importlib.import_module("tests.test_snapshot_refresh_manual_endpoint_integration"),
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
REFRESH_PATH = "/api/v1/snapshot-refresh/recalculate"
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"
MANIFEST_FIELDS = (
    "timestamp",
    "granularity",
    "currency",
    "calculationVersion",
    "accounts",
)
FORBIDDEN_FIELDS = {
    "userId",
    "email",
    "membership",
    "role",
    "relationType",
    "invitedBy",
    "mode",
    "disposition",
    "selectedItemIds",
    "priceSource",
    "priceSnapshotId",
    "exchangeRateId",
    "exchangeRates",
    "cashValueByCurrency",
    "investmentValueByCurrency",
    "liabilitiesValueByCurrency",
    "calculatedAt",
    "createdAt",
    "updatedAt",
    "writerCommand",
    "internalError",
}


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret="5m-a-manifest-integration-secret-32",
        _env_file=None,
    )


def _app(
    prefix: str,
    *,
    session_states: list[bool] | None = None,
):
    app = create_app(_settings())
    app.dependency_overrides[get_current_principal] = lambda: manual_support._principal(
        manual_support._user_id(prefix)
    )
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: (
        lambda: manual_support.BUCKET
    )
    if session_states is not None:

        async def session_override() -> AsyncIterator[AsyncSession]:
            async with AsyncSession(
                app.state.database.engine,
                expire_on_commit=False,
            ) as session:
                yield session
                session_states.append(session.in_transaction())

        app.dependency_overrides[get_db_session] = session_override
    return app


def _manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in MANIFEST_FIELDS}


def _error_contract(response: Any) -> None:
    assert response.status_code == 409
    error = response.json()["error"]
    assert error == {
        "code": "portfolio_snapshot_unavailable",
        "message": "The requested portfolio snapshot is unavailable.",
        "request_id": error["request_id"],
    }


def _audit_no_leakage(value: object) -> None:
    if isinstance(value, dict):
        assert FORBIDDEN_FIELDS.isdisjoint(value)
        for child in value.values():
            _audit_no_leakage(child)
    elif isinstance(value, list):
        for child in value:
            _audit_no_leakage(child)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    ],
)
async def test_single_supported_account_manifest_opens_both_exact_reads(
    account_type: AccountType,
) -> None:
    prefix = f"5ma-single-{account_type.value}"
    await manual_support._seed(
        prefix,
        (manual_support._AccountSpec("account", account_type=account_type),),
    )
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            assert refresh.status_code == 200
            manifest = _manifest(refresh.json())
            portfolio = client.post(PORTFOLIO_PATH, json=manifest)
            dashboard = client.post(DASHBOARD_PATH, json=manifest)

        assert portfolio.status_code == dashboard.status_code == 200
        assert refresh.json()["timestamp"] == portfolio.json()["timestamp"]
        assert refresh.json()["timestamp"] == dashboard.json()["timestamp"]
        assert refresh.json()["granularity"] == portfolio.json()["granularity"]
        assert refresh.json()["granularity"] == dashboard.json()["granularity"]
        assert refresh.json()["currency"] == portfolio.json()["currency"]
        assert refresh.json()["currency"] == dashboard.json()["currency"]
        assert (
            refresh.json()["calculationVersion"]
            == portfolio.json()["calculationVersion"]
            == dashboard.json()["calculationVersion"]
        )
        assert refresh.json()["accounts"] == [
            {
                "accountId": manual_support._account_id(prefix, "account"),
                "snapshotId": portfolio.json()["accounts"][0]["snapshotId"],
            }
        ]
        assert {account["account"]["accountId"] for account in portfolio.json()["accounts"]} == {
            manual_support._account_id(prefix, "account")
        }
        assert {account["accountId"] for account in dashboard.json()["accounts"]} == {
            manual_support._account_id(prefix, "account")
        }
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_multiple_investment_accounts_use_complete_manifest() -> None:
    prefix = "5ma-multi-investment"
    specs = (
        manual_support._AccountSpec("broker", account_type=AccountType.broker),
        manual_support._AccountSpec("exchange", account_type=AccountType.exchange),
        manual_support._AccountSpec("wallet", account_type=AccountType.crypto_wallet),
    )
    await manual_support._seed(prefix, specs)
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            manifest = _manifest(refresh.json())
            portfolio = client.post(PORTFOLIO_PATH, json=manifest)
            dashboard = client.post(DASHBOARD_PATH, json=manifest)

        assert refresh.status_code == portfolio.status_code == dashboard.status_code == 200
        expected_ids = {manual_support._account_id(prefix, spec.suffix) for spec in specs}
        assert {item["accountId"] for item in manifest["accounts"]} == expected_ids
        assert {
            item["account"]["accountId"] for item in portfolio.json()["accounts"]
        } == expected_ids
        assert {item["accountId"] for item in dashboard.json()["accounts"]} == expected_ids
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_investment_and_liability_manifest_preserves_snapshot_ids() -> None:
    prefix = "5ma-investment-liability"
    specs = (
        manual_support._AccountSpec("broker", account_type=AccountType.broker),
        manual_support._AccountSpec("loan", account_type=AccountType.loan),
    )
    await manual_support._seed(prefix, specs)
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            manifest = _manifest(refresh.json())
            portfolio = client.post(PORTFOLIO_PATH, json=manifest)
            dashboard = client.post(DASHBOARD_PATH, json=manifest)

        assert refresh.status_code == portfolio.status_code == dashboard.status_code == 200
        manifest_ids = {item["accountId"]: item["snapshotId"] for item in manifest["accounts"]}
        portfolio_ids = {
            item["account"]["accountId"]: item["snapshotId"]
            for item in portfolio.json()["accounts"]
        }
        assert portfolio_ids == manifest_ids
        assert {item["accountId"] for item in dashboard.json()["accounts"]} == set(manifest_ids)
        assert dashboard.json()["summary"]["liabilityAccountCount"] == 1
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_refresh_and_reuse_only_accounts_are_both_mandatory() -> None:
    prefix = "5ma-refresh-reuse"
    specs = (
        manual_support._AccountSpec("owner", AccountMemberRole.owner),
        manual_support._AccountSpec("viewer", AccountMemberRole.viewer),
    )
    await manual_support._seed(prefix, specs)
    viewer_snapshot_id = await manual_support._write_viewer_snapshot(prefix, "viewer")
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            manifest = _manifest(refresh.json())
            portfolio = client.post(PORTFOLIO_PATH, json=manifest)
            dashboard = client.post(DASHBOARD_PATH, json=manifest)

        assert refresh.status_code == portfolio.status_code == dashboard.status_code == 200
        assert refresh.json()["refreshAccountCount"] == 1
        assert refresh.json()["reuseOnlyAccountCount"] == 1
        assert refresh.json()["reusedAccountSnapshotCount"] == 1
        assert len(manifest["accounts"]) == refresh.json()["selectedAccountSnapshotCount"] == 2
        viewer = next(
            item
            for item in manifest["accounts"]
            if item["accountId"] == manual_support._account_id(prefix, "viewer")
        )
        assert viewer["snapshotId"] == viewer_snapshot_id
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        AccountMemberRole.owner,
        AccountMemberRole.admin,
        AccountMemberRole.editor,
        AccountMemberRole.viewer,
    ],
)
async def test_existing_refresh_role_policy_produces_usable_manifest(
    role: AccountMemberRole,
) -> None:
    prefix = f"5ma-role-{role.value}"
    await manual_support._seed(
        prefix,
        (manual_support._AccountSpec("account", role),),
    )
    if role is AccountMemberRole.viewer:
        await manual_support._write_viewer_snapshot(prefix, "account")
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            portfolio = client.post(PORTFOLIO_PATH, json=_manifest(refresh.json()))
            dashboard = client.post(DASHBOARD_PATH, json=_manifest(refresh.json()))

        assert refresh.status_code == portfolio.status_code == dashboard.status_code == 200
        if role is AccountMemberRole.viewer:
            assert refresh.json()["reuseOnlyAccountCount"] == 1
            assert refresh.json()["reusedAccountSnapshotCount"] == 1
        else:
            assert refresh.json()["refreshAccountCount"] == 1
            assert refresh.json()["createdAccountSnapshotCount"] == 1
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_same_bucket_replay_preserves_byte_identical_manifest() -> None:
    prefix = "5ma-replay"
    await manual_support._seed(
        prefix,
        (manual_support._AccountSpec("account"),),
    )
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            created = client.post(REFRESH_PATH)
            replayed = client.post(REFRESH_PATH)
            portfolio = client.post(PORTFOLIO_PATH, json=_manifest(replayed.json()))

        assert created.status_code == replayed.status_code == portfolio.status_code == 200
        assert created.json()["netWorthStatus"] == "created"
        assert replayed.json()["netWorthStatus"] == "replayed"
        assert created.json()["createdAccountSnapshotCount"] == 1
        assert replayed.json()["replayedAccountSnapshotCount"] == 1
        assert _manifest(created.json()) == _manifest(replayed.json())
        assert (
            replayed.json()["accounts"][0]["snapshotId"]
            == (portfolio.json()["accounts"][0]["snapshotId"])
        )
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suffixes",
    [
        ("z", "a", "m"),
        ("m", "z", "a"),
        ("a", "m", "z"),
    ],
)
async def test_manifest_order_is_canonical_despite_seed_order(
    suffixes: tuple[str, ...],
) -> None:
    label = "-".join(suffixes)
    prefix = f"5ma-order-{label}"
    await manual_support._seed(
        prefix,
        tuple(manual_support._AccountSpec(suffix) for suffix in suffixes),
    )
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            replayed = client.post(REFRESH_PATH)

        assert refresh.status_code == replayed.status_code == 200
        account_ids = [item["accountId"] for item in refresh.json()["accounts"]]
        assert account_ids == sorted(account_ids)
        assert replayed.json()["accounts"] == refresh.json()["accounts"]
        assert len(account_ids) == len(set(account_ids))
        snapshot_ids = [item["snapshotId"] for item in refresh.json()["accounts"]]
        assert len(snapshot_ids) == len(set(snapshot_ids))
        assert len(account_ids) == refresh.json()["selectedAccountSnapshotCount"]
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshotId", "tampered-snapshot"),
        ("currency", "USD"),
        ("calculationVersion", 2),
        ("timestamp", "2036-07-29T14:36:00.000"),
    ],
)
async def test_tampered_manifest_never_falls_back(
    path: str,
    field: str,
    value: object,
) -> None:
    prefix = f"5ma-tamper-{path.split('/')[-2]}-{field}"
    await manual_support._seed(
        prefix,
        (manual_support._AccountSpec("account"),),
    )
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            manifest = deepcopy(_manifest(refresh.json()))
            if field == "snapshotId":
                manifest["accounts"][0]["snapshotId"] = value
            else:
                manifest[field] = value
            response = client.post(path, json=manifest)

        _error_contract(response)
        assert manual_support._account_id(prefix, "account") not in response.text
        assert "tampered-snapshot" not in response.text
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_one_tampered_guard_rejects_complete_multi_account_read() -> None:
    prefix = "5ma-no-partial"
    await manual_support._seed(
        prefix,
        (
            manual_support._AccountSpec("a"),
            manual_support._AccountSpec("b"),
        ),
    )
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            refresh = client.post(REFRESH_PATH)
            manifest = deepcopy(_manifest(refresh.json()))
            manifest["accounts"][1]["snapshotId"] = "wrong-snapshot"
            portfolio = client.post(PORTFOLIO_PATH, json=manifest)
            dashboard = client.post(DASHBOARD_PATH, json=manifest)

        for response in (portfolio, dashboard):
            _error_contract(response)
            assert "accounts" not in response.json()
            assert all(
                item["accountId"] not in response.text for item in refresh.json()["accounts"]
            )
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_refresh_session_is_idle_after_manifest_response() -> None:
    prefix = "5ma-session-idle"
    await manual_support._seed(
        prefix,
        (manual_support._AccountSpec("account"),),
    )
    states: list[bool] = []
    try:
        app = _app(prefix, session_states=states)
        with TestClient(app) as client:
            response = client.post(REFRESH_PATH)

        assert response.status_code == 200
        assert states == [False]
    finally:
        await manual_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_refresh_manifest_response_has_only_approved_public_lineage() -> None:
    prefix = "5ma-leakage"
    await manual_support._seed(
        prefix,
        (
            manual_support._AccountSpec("owner"),
            manual_support._AccountSpec("viewer", AccountMemberRole.viewer),
        ),
    )
    await manual_support._write_viewer_snapshot(prefix, "viewer")
    try:
        app = _app(prefix)
        with TestClient(app) as client:
            response = client.post(REFRESH_PATH)

        assert response.status_code == 200
        _audit_no_leakage(response.json())
        assert all(set(item) == {"accountId", "snapshotId"} for item in response.json()["accounts"])
        assert len(response.json()["accounts"]) == response.json()["selectedAccountSnapshotCount"]
    finally:
        await manual_support._cleanup(prefix)


def test_no_additional_refresh_or_read_endpoint_is_registered() -> None:
    paths = create_app(_settings()).openapi()["paths"]
    refresh_paths = [path for path in paths if "snapshot-refresh" in path]
    assert refresh_paths == [REFRESH_PATH]
    assert set(paths[REFRESH_PATH]) == {"post"}
    assert set(paths[PORTFOLIO_PATH]) == {"post"}
    assert set(paths[DASHBOARD_PATH]) == {"post"}
