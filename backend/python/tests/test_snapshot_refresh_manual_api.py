from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import SnapshotGranularity
from app.main import create_app
from app.modules.portfolio_snapshot.multi_account_api_models import (
    ExactPortfolioSnapshotSetRequest,
)
from app.modules.snapshot_refresh.manual_service import (
    ManualUserSnapshotRefreshService,
    RecalculateUserSnapshotRefreshResult,
    SnapshotRefreshAccountSelection,
    UserSnapshotRefreshConflictError,
    UserSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.models import (
    SnapshotRefreshAccountSelectionResponse,
    UserSnapshotRefreshRecalculateResponse,
)

BUCKET = datetime(2036, 4, 5, 10, 20)


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


def _result() -> RecalculateUserSnapshotRefreshResult:
    return RecalculateUserSnapshotRefreshResult(
        net_worth_snapshot_id="net-worth-a",
        net_worth_status="created",
        timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        currency="EUR",
        calculation_version=1,
        accounts=(
            SnapshotRefreshAccountSelection("account-a", "snapshot-account-a"),
            SnapshotRefreshAccountSelection("account-b", "snapshot-account-b"),
            SnapshotRefreshAccountSelection("account-c", "snapshot-account-c"),
        ),
        refresh_account_count=2,
        reuse_only_account_count=1,
        created_account_snapshot_count=1,
        replayed_account_snapshot_count=1,
        reused_account_snapshot_count=1,
        selected_account_snapshot_count=3,
    )


def _client(
    settings: Settings,
    *,
    principal: AuthenticatedPrincipal | None = None,
) -> tuple[TestClient, AsyncSession]:
    app = create_app(settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app), session


def test_openapi_contract_has_no_body_or_selectors_and_requires_auth(
    test_settings: Settings,
) -> None:
    schema = create_app(test_settings).openapi()
    path = "/api/v1/snapshot-refresh/recalculate"
    operation = schema["paths"][path]["post"]

    assert "requestBody" not in operation
    assert operation.get("parameters", []) == []
    assert operation["tags"] == ["snapshot-refresh"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserSnapshotRefreshRecalculateResponse"
    }
    assert path not in {
        route_path
        for route in create_app(test_settings).routes
        if isinstance((route_path := getattr(route, "path", None)), str)
        if not getattr(route, "include_in_schema", True)
    }


def test_missing_and_invalid_auth_do_not_open_database_session(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    session_calls = 0

    async def session_override() -> AsyncIterator[AsyncSession]:
        nonlocal session_calls
        session_calls += 1
        yield cast(AsyncSession, AsyncMock(spec=AsyncSession))

    app.dependency_overrides[get_db_session] = session_override
    with TestClient(app) as client:
        missing = client.post("/api/v1/snapshot-refresh/recalculate")
        invalid = client.post(
            "/api/v1/snapshot-refresh/recalculate",
            headers={"Authorization": "Bearer invalid"},
        )

    assert (missing.status_code, missing.json()["error"]["code"]) == (
        401,
        "authentication_required",
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (
        401,
        "invalid_session_token",
    )
    assert session_calls == 0


def test_thin_adapter_forwards_only_principal_and_returns_camel_case(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recalculate = AsyncMock(return_value=_result())
    monkeypatch.setattr(
        ManualUserSnapshotRefreshService,
        "recalculate",
        recalculate,
    )
    client, _ = _client(test_settings, principal=_principal())

    with client:
        response = client.post("/api/v1/snapshot-refresh/recalculate")

    assert response.status_code == 200
    assert response.json() == {
        "netWorthSnapshotId": "net-worth-a",
        "netWorthStatus": "created",
        "timestamp": "2036-04-05T10:20:00.000",
        "granularity": "minute",
        "currency": "EUR",
        "calculationVersion": 1,
        "accounts": [
            {
                "accountId": "account-a",
                "snapshotId": "snapshot-account-a",
            },
            {
                "accountId": "account-b",
                "snapshotId": "snapshot-account-b",
            },
            {
                "accountId": "account-c",
                "snapshotId": "snapshot-account-c",
            },
        ],
        "refreshAccountCount": 2,
        "reuseOnlyAccountCount": 1,
        "createdAccountSnapshotCount": 1,
        "replayedAccountSnapshotCount": 1,
        "reusedAccountSnapshotCount": 1,
        "selectedAccountSnapshotCount": 3,
    }
    recalculate.assert_awaited_once()
    assert recalculate.await_args is not None
    command = recalculate.await_args.args[0]
    assert command.principal == _principal()
    assert tuple(command.__slots__) == ("principal",)


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            UserSnapshotRefreshUnavailableError(),
            "snapshot_refresh_unavailable",
            "Snapshot refresh cannot be completed from the current account data.",
        ),
        (
            UserSnapshotRefreshConflictError(),
            "snapshot_refresh_conflict",
            "Snapshot refresh conflicts with existing data.",
        ),
    ],
)
def test_public_errors_are_exact_generic_409_payloads(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
    message: str,
) -> None:
    monkeypatch.setattr(
        ManualUserSnapshotRefreshService,
        "recalculate",
        AsyncMock(side_effect=error),
    )
    client, _ = _client(test_settings, principal=_principal())

    with client:
        response = client.post("/api/v1/snapshot-refresh/recalculate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    for forbidden in (
        "user-a",
        "account-",
        "snapshot-",
        "EUR",
        "USD",
        "2036-",
    ):
        assert forbidden not in response.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("userId", "user-a"),
        ("accountIds", ["account-a"]),
        ("accountSnapshots", []),
        ("requiredAccountSnapshotIdentities", []),
        ("selectedAccountSnapshotIds", []),
        ("projection", {}),
        ("audit", {}),
        ("exchangeRates", {}),
    ],
)
def test_response_rejects_internal_extra_fields(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "net_worth_snapshot_id": "net-worth-a",
        "net_worth_status": "created",
        "timestamp": BUCKET,
        "granularity": "minute",
        "currency": "EUR",
        "calculation_version": 1,
        "accounts": [
            {
                "account_id": "account-a",
                "snapshot_id": "snapshot-account-a",
            },
            {
                "account_id": "account-b",
                "snapshot_id": "snapshot-account-b",
            },
            {
                "account_id": "account-c",
                "snapshot_id": "snapshot-account-c",
            },
        ],
        "refresh_account_count": 2,
        "reuse_only_account_count": 1,
        "created_account_snapshot_count": 1,
        "replayed_account_snapshot_count": 1,
        "reused_account_snapshot_count": 1,
        "selected_account_snapshot_count": 3,
        field: value,
    }
    with pytest.raises(ValidationError):
        UserSnapshotRefreshRecalculateResponse.model_validate(payload)


def test_existing_routes_remain_unique_and_new_route_has_no_legacy_alias(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    paths = list(app.openapi()["paths"])
    assert paths.count("/api/v1/snapshot-refresh/recalculate") == 1
    assert "/snapshot-refresh/recalculate" not in paths
    assert "/api/v1/accounts/{account_id}/snapshots/recalculate" in paths
    assert "/api/v1/net-worth/snapshots/recalculate" in paths
    assert "/api/v1/health/live" in paths
    operation_ids = [
        operation["operationId"]
        for path in create_app(test_settings).openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))


def test_manifest_subset_is_directly_valid_for_both_5l_request_consumers(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recalculate = AsyncMock(return_value=_result())
    monkeypatch.setattr(
        ManualUserSnapshotRefreshService,
        "recalculate",
        recalculate,
    )
    client, _ = _client(test_settings, principal=_principal())

    with client:
        response = client.post("/api/v1/snapshot-refresh/recalculate")

    assert response.status_code == 200
    payload = response.json()
    manifest = {
        key: payload[key]
        for key in (
            "timestamp",
            "granularity",
            "currency",
            "calculationVersion",
            "accounts",
        )
    }
    validated = ExactPortfolioSnapshotSetRequest.model_validate(manifest)
    assert validated.timestamp == BUCKET
    assert validated.granularity.value == "minute"
    assert validated.currency == "EUR"
    assert validated.calculation_version == 1
    assert tuple(item.account_id for item in validated.accounts) == (
        "account-a",
        "account-b",
        "account-c",
    )
    assert tuple(item.snapshot_id for item in validated.accounts) == (
        "snapshot-account-a",
        "snapshot-account-b",
        "snapshot-account-c",
    )


def test_manifest_models_are_exact_extra_forbid_camel_case_contracts() -> None:
    assert set(SnapshotRefreshAccountSelectionResponse.model_fields) == {
        "account_id",
        "snapshot_id",
    }
    assert set(UserSnapshotRefreshRecalculateResponse.model_fields) == {
        "net_worth_snapshot_id",
        "net_worth_status",
        "timestamp",
        "granularity",
        "currency",
        "calculation_version",
        "accounts",
        "refresh_account_count",
        "reuse_only_account_count",
        "created_account_snapshot_count",
        "replayed_account_snapshot_count",
        "reused_account_snapshot_count",
        "selected_account_snapshot_count",
    }
    assert SnapshotRefreshAccountSelectionResponse.model_config["extra"] == "forbid"
    assert UserSnapshotRefreshRecalculateResponse.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        SnapshotRefreshAccountSelectionResponse.model_validate(
            {
                "accountId": "account-a",
                "snapshotId": "snapshot-a",
                "mode": "refresh",
            }
        )


def test_openapi_exposes_additive_required_manifest_without_new_route(
    test_settings: Settings,
) -> None:
    schema = create_app(test_settings).openapi()
    response_schema = schema["components"]["schemas"]["UserSnapshotRefreshRecalculateResponse"]
    account_schema = schema["components"]["schemas"]["SnapshotRefreshAccountSelectionResponse"]

    assert "calculationVersion" in response_schema["required"]
    assert "accounts" in response_schema["required"]
    assert response_schema["properties"]["accounts"]["items"] == {
        "$ref": "#/components/schemas/SnapshotRefreshAccountSelectionResponse"
    }
    assert account_schema["required"] == ["accountId", "snapshotId"]
    assert set(account_schema["properties"]) == {"accountId", "snapshotId"}
    refresh_paths = [path for path in schema["paths"] if "snapshot-refresh" in path]
    assert refresh_paths == ["/api/v1/snapshot-refresh/recalculate"]


def test_success_response_leaks_only_approved_account_manifest(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ManualUserSnapshotRefreshService,
        "recalculate",
        AsyncMock(return_value=_result()),
    )
    client, _ = _client(test_settings, principal=_principal())

    with client:
        response = client.post("/api/v1/snapshot-refresh/recalculate")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["accounts"][0]) == {"accountId", "snapshotId"}
    forbidden = {
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

    def audit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                audit(child)
        elif isinstance(value, list):
            for child in value:
                audit(child)

    audit(payload)
    assert payload["timestamp"] == "2036-04-05T10:20:00.000"
