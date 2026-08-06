"""PostgreSQL cross-endpoint and transaction evidence for the final 5L audit."""

from __future__ import annotations

import asyncio
import importlib
import os
import threading
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountType
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.main import create_app
from app.modules.portfolio_snapshot.repository import PortfolioSnapshotRepository

single_support = cast(
    Any,
    importlib.import_module("tests.test_portfolio_snapshot_api_integration"),
)
multi_support = cast(
    Any,
    importlib.import_module("tests.test_portfolio_dashboard_snapshot_api_integration"),
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = single_support.SNAPSHOT_AT
CREATED_AT = single_support.CREATED_AT
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"
FINANCIAL_KEYS = {
    "cashValue",
    "investmentValue",
    "investmentCostBasis",
    "liabilitiesValue",
    "totalValue",
    "netDepositsValue",
    "realizedPnlValue",
    "unrealizedPnlValue",
    "feesValue",
    "taxesValue",
    "assetsValue",
    "quantity",
    "pricePerUnit",
    "value",
    "costBasis",
    "unrealizedPnl",
    "allocationPct",
    "nativeValue",
    "nativeCostBasis",
    "amount",
}
LEAKED_KEYS = {
    "userId",
    "email",
    "membership",
    "member",
    "role",
    "relationType",
    "invitedBy",
    "selectedItemIds",
    "priceSource",
    "priceSnapshotId",
    "exchangeRateId",
    "exchangeRates",
    "investmentValueByCurrency",
    "investmentCostBasisByCurrency",
    "realizedPnlByCurrency",
    "unrealizedPnlByCurrency",
    "feesByCurrency",
    "taxesByCurrency",
    "calculatedAt",
    "createdAt",
    "updatedAt",
    "passwordHash",
}
DASHBOARD_FORBIDDEN_KEYS = {
    "cashByCurrency",
    "netDepositsByCurrency",
    "quantity",
    "pricePerUnit",
    "priceCurrency",
    "priceTimestamp",
    "costBasis",
    "costCurrency",
    "nativeValue",
    "nativeValueCurrency",
    "nativeCostBasis",
    "nativeCostCurrency",
    "source",
}


def _single_path(account_id: str) -> str:
    return f"/api/v1/portfolio/accounts/{account_id}/snapshot"


def _path_label(path: str) -> str:
    return "single" if path == "single" else path.split("/")[-2]


def _single_call(
    account_id: str,
    user_id: str,
    *,
    params: dict[str, str] | None = None,
    sql: list[tuple[str, int]] | None = None,
    session_states: list[bool] | None = None,
):
    app = create_app(single_support._settings())
    with TestClient(app) as client:
        database = app.state.database
        if session_states is not None:

            async def session_override() -> AsyncIterator[AsyncSession]:
                async with AsyncSession(database.engine, expire_on_commit=False) as session:
                    yield session
                    session_states.append(session.in_transaction())

            app.dependency_overrides[get_db_session] = session_override
        if sql is not None:

            def capture(
                connection: Any,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                transaction = connection.get_transaction()
                sql.append((statement, id(transaction)))

            event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
        return client.get(
            _single_path(account_id),
            params=params or single_support._params(),
            headers=single_support._headers(user_id),
        )


def _portfolio_call(
    user_id: str,
    accounts: tuple[str, ...],
    *,
    snapshot_ids: tuple[str | None, ...] | None = None,
    **changes: object,
):
    return multi_support._call(
        PORTFOLIO_PATH,
        user_id,
        multi_support._body(
            accounts,
            snapshot_ids=snapshot_ids,
            **changes,
        ),
    )


def _dashboard_call(
    user_id: str,
    accounts: tuple[str, ...],
    *,
    snapshot_ids: tuple[str | None, ...] | None = None,
    **changes: object,
):
    return multi_support._call(
        DASHBOARD_PATH,
        user_id,
        multi_support._body(
            accounts,
            snapshot_ids=snapshot_ids,
            **changes,
        ),
    )


def _error_contract(response: Any, status: int, code: str, message: str) -> None:
    assert response.status_code == status
    error = response.json()["error"]
    assert error == {
        "code": code,
        "message": message,
        "request_id": error["request_id"],
    }


def _assert_public_json(value: object, *, dashboard: bool = False) -> None:
    if isinstance(value, dict):
        assert LEAKED_KEYS.isdisjoint(value)
        if dashboard:
            assert DASHBOARD_FORBIDDEN_KEYS.isdisjoint(value)
        for key, child in value.items():
            if key in FINANCIAL_KEYS:
                assert isinstance(child, str)
                Decimal(child)
            _assert_public_json(child, dashboard=dashboard)
    elif isinstance(value, list):
        for child in value:
            _assert_public_json(child, dashboard=dashboard)
    else:
        assert not isinstance(value, float)


def _assert_transaction_evidence(
    sql: list[tuple[str, int]],
    *,
    account_count: int,
) -> None:
    normalized = [" ".join(statement.lower().split()) for statement, _ in sql]
    isolation = "set transaction isolation level repeatable read"
    assert normalized.count(isolation) == 1
    isolation_index = normalized.index(isolation)
    assert isolation_index > 0
    financial_transaction = sql[isolation_index][1]
    assert (
        min(
            index
            for index, (_, transaction) in enumerate(sql)
            if transaction == financial_transaction
        )
        == isolation_index
    )
    assert all(transaction == financial_transaction for _, transaction in sql[isolation_index:])
    assert any(transaction != financial_transaction for _, transaction in sql[:isolation_index])
    financial_sql = normalized[isolation_index:]
    assert sum('"accountmember"' in statement for statement in financial_sql) == account_count
    for table in (
        '"account"',
        '"accountsnapshot"',
        '"accountsnapshotitem"',
        '"assetlisting"',
        '"asset"',
    ):
        assert any(table in statement for statement in financial_sql)
    assert all(
        not statement.lstrip().startswith(("insert ", "update ", "delete "))
        for statement in financial_sql
    )
    assert all("for update" not in statement for statement in financial_sql)
    assert all("advisory" not in statement for statement in financial_sql)
    assert all("lock table" not in statement for statement in financial_sql)


async def _persisted_counts(prefix: str) -> tuple[int, int, int, int]:
    engine = single_support._engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            snapshot_ids = select(AccountSnapshotModel.id).where(
                AccountSnapshotModel.account_id.in_(account_ids)
            )
            return (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountModel)
                        .where(AccountModel.id.in_(account_ids))
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountMemberModel)
                        .where(AccountMemberModel.account_id.in_(account_ids))
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.id.in_(snapshot_ids))
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                    )
                    or 0
                ),
            )
    finally:
        await engine.dispose()


def _account_names(payload: dict[str, Any], path: str) -> set[str]:
    if path == PORTFOLIO_PATH:
        return {entry["account"]["name"] for entry in payload["accounts"]}
    return {entry["name"] for entry in payload["accounts"]}


@pytest.mark.asyncio
async def test_single_multi_and_dashboard_share_one_exact_broker_view() -> None:
    prefix = single_support._prefix("5l-audit-cross")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(prefix)
        single = _single_call(account_id, user_id)
        multi = _portfolio_call(
            user_id,
            (account_id,),
            snapshot_ids=(snapshot_id,),
        )
        dashboard = _dashboard_call(
            user_id,
            (account_id,),
            snapshot_ids=(snapshot_id,),
        )

        assert single.status_code == multi.status_code == dashboard.status_code == 200
        single_payload = single.json()
        multi_payload = multi.json()
        dashboard_payload = dashboard.json()
        contribution = multi_payload["accounts"][0]
        assert contribution == {
            "snapshotId": single_payload["snapshotId"],
            "account": single_payload["account"],
            "source": single_payload["source"],
            "summary": single_payload["summary"],
            "positions": single_payload["positions"],
        }
        for key in ("timestamp", "granularity", "currency", "calculationVersion"):
            assert multi_payload[key] == single_payload[key]
            assert dashboard_payload[key] == single_payload[key]
        assert dashboard_payload["summary"]["totalValue"] == multi_payload["summary"]["totalValue"]
        assert (
            dashboard_payload["summary"]["investmentValue"]
            == multi_payload["summary"]["investmentValue"]
        )
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_portfolio_exposes_exact_persisted_currency_breakdowns_without_dashboard_drift() -> (
    None
):
    prefix = single_support._prefix("r6a-breakdowns")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        engine = single_support._engine()
        try:
            async with AsyncSession(engine) as session:
                await session.execute(
                    update(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id == snapshots[0])
                    .values(
                        cash_value=Decimal("15.000000"),
                        cash_value_by_currency={
                            "CZK": "10000.000000",
                            "EUR": "500.000000",
                        },
                        net_deposits_value=Decimal("30.000000"),
                        net_deposits_by_currency={"CZK": "25000.000000"},
                        total_value=Decimal("115.000000"),
                    )
                )
                await session.execute(
                    update(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id == snapshots[1])
                    .values(
                        cash_value=Decimal("-5.000000"),
                        cash_value_by_currency={
                            "USD": "-50.000000",
                            "EUR": "100.000000",
                        },
                        net_deposits_value=Decimal("-5.000000"),
                        net_deposits_by_currency={"EUR": "-5.000000"},
                        total_value=Decimal("95.000000"),
                    )
                )
                await session.commit()
                rows = tuple(
                    await session.execute(
                        select(
                            AccountSnapshotModel.id,
                            AccountSnapshotModel.cash_value_by_currency,
                            AccountSnapshotModel.net_deposits_by_currency,
                        )
                        .where(AccountSnapshotModel.id.in_(snapshots))
                        .order_by(AccountSnapshotModel.id)
                    )
                )
        finally:
            await engine.dispose()

        assert {row.id: row.cash_value_by_currency for row in rows} == {
            snapshots[0]: {"CZK": "10000.000000", "EUR": "500.000000"},
            snapshots[1]: {"EUR": "100.000000", "USD": "-50.000000"},
        }
        assert {row.id: row.net_deposits_by_currency for row in rows} == {
            snapshots[0]: {"CZK": "25000.000000"},
            snapshots[1]: {"EUR": "-5.000000"},
        }

        singles = tuple(
            _single_call(
                account_id,
                user_id,
                params=single_support._params(snapshotId=snapshot_id),
            )
            for account_id, snapshot_id in zip(accounts, snapshots, strict=True)
        )
        portfolio = _portfolio_call(user_id, accounts, snapshot_ids=snapshots)
        dashboard = _dashboard_call(user_id, accounts, snapshot_ids=snapshots)

        assert all(response.status_code == 200 for response in singles)
        assert portfolio.status_code == dashboard.status_code == 200
        assert singles[0].json()["snapshotId"] == snapshots[0]
        assert singles[1].json()["snapshotId"] == snapshots[1]
        assert singles[0].json()["summary"]["cashByCurrency"] == [
            {"currency": "CZK", "amount": "10000.000000"},
            {"currency": "EUR", "amount": "500.000000"},
        ]
        assert singles[1].json()["summary"]["cashByCurrency"] == [
            {"currency": "EUR", "amount": "100.000000"},
            {"currency": "USD", "amount": "-50.000000"},
        ]

        portfolio_payload = portfolio.json()
        portfolio_summary = portfolio_payload["summary"]
        assert [account["snapshotId"] for account in portfolio_payload["accounts"]] == list(
            snapshots
        )
        assert portfolio_summary["cashValue"] == "10.000000"
        assert portfolio_summary["cashByCurrency"] == [
            {"currency": "CZK", "amount": "10000.000000"},
            {"currency": "EUR", "amount": "600.000000"},
            {"currency": "USD", "amount": "-50.000000"},
        ]
        assert portfolio_summary["netDepositsValue"] == "25.000000"
        assert portfolio_summary["netDepositsByCurrency"] == [
            {"currency": "CZK", "amount": "25000.000000"},
            {"currency": "EUR", "amount": "-5.000000"},
        ]
        assert [
            account["summary"]["cashByCurrency"] for account in portfolio_payload["accounts"]
        ] == [
            singles[0].json()["summary"]["cashByCurrency"],
            singles[1].json()["summary"]["cashByCurrency"],
        ]

        dashboard_payload = dashboard.json()
        for key in (
            "cashValue",
            "investmentValue",
            "investmentCostBasis",
            "liabilitiesValue",
            "totalValue",
            "netDepositsValue",
        ):
            assert dashboard_payload["summary"][key] == portfolio_summary[key]
        _assert_public_json(portfolio_payload)
        _assert_public_json(dashboard_payload, dashboard=True)
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.exchange, AccountType.crypto_wallet],
)
async def test_broker_and_other_investment_account_shapes(
    account_type: AccountType,
) -> None:
    prefix = single_support._prefix(f"5l-audit-investment-{account_type.value}")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(
            prefix,
            second_type=account_type,
        )
        response = _portfolio_call(user_id, accounts, snapshot_ids=snapshots)

        assert response.status_code == 200
        assert response.json()["summary"]["accountCount"] == 2
        assert len(response.json()["accounts"][1]["positions"]) == 2
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
async def test_investment_and_liability_shapes(account_type: AccountType) -> None:
    prefix = single_support._prefix(f"5l-audit-mixed-{account_type.value}")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(
            prefix,
            second_type=account_type,
        )
        response = _portfolio_call(user_id, accounts, snapshot_ids=snapshots)

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["liabilitiesValue"] == "25.000000"
        liability = next(
            entry
            for entry in payload["accounts"]
            if entry["account"]["accountType"] == account_type.value
        )
        assert liability["positions"] == []
        assert liability["summary"]["totalValue"] == "-25.000000"
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
async def test_liability_only_dashboard_has_no_investment_breakdown(
    account_type: AccountType,
) -> None:
    prefix = single_support._prefix(f"5l-audit-liability-{account_type.value}")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(
            prefix,
            account_type=account_type,
        )
        response = _dashboard_call(
            user_id,
            (account_id,),
            snapshot_ids=(snapshot_id,),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["liabilityAccountCount"] == 1
        assert payload["summary"]["totalValue"] == "-25.000000"
        assert payload["assetTypeAllocations"] == []
        assert payload["topPositions"] == []
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_empty_investment_dashboard_has_no_investment_breakdown() -> None:
    prefix = single_support._prefix("5l-audit-empty")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(
            prefix,
            empty=True,
        )
        response = _dashboard_call(
            user_id,
            (account_id,),
            snapshot_ids=(snapshot_id,),
        )

        assert response.status_code == 200
        assert response.json()["summary"]["positionCount"] == 0
        assert response.json()["assetTypeAllocations"] == []
        assert response.json()["topPositions"] == []
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_multi_summary_and_dashboard_summary_are_exact_sums() -> None:
    prefix = single_support._prefix("5l-audit-summary")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        singles = [_single_call(account_id, user_id).json() for account_id in accounts]
        portfolio = _portfolio_call(user_id, accounts, snapshot_ids=snapshots)
        dashboard = _dashboard_call(user_id, accounts, snapshot_ids=snapshots)

        assert portfolio.status_code == dashboard.status_code == 200
        portfolio_summary = portfolio.json()["summary"]
        for key in (
            "cashValue",
            "investmentValue",
            "investmentCostBasis",
            "liabilitiesValue",
            "totalValue",
            "netDepositsValue",
            "realizedPnlValue",
            "unrealizedPnlValue",
            "feesValue",
            "taxesValue",
        ):
            assert Decimal(portfolio_summary[key]) == sum(
                (Decimal(single["summary"][key]) for single in singles),
                Decimal(0),
            )
        dashboard_summary = dashboard.json()["summary"]
        assert dashboard_summary["totalValue"] == portfolio_summary["totalValue"]
        assert dashboard_summary["liabilitiesValue"] == portfolio_summary["liabilitiesValue"]
        assert dashboard_summary["investmentValue"] == portfolio_summary["investmentValue"]
        assert dashboard_summary["investmentCostBasis"] == portfolio_summary["investmentCostBasis"]
        assert dashboard_summary["unrealizedPnlValue"] == portfolio_summary["unrealizedPnlValue"]
        assert dashboard_summary["accountCount"] == portfolio_summary["accountCount"]
        assert dashboard_summary["positionCount"] == portfolio_summary["positionCount"]
        assert Decimal(dashboard_summary["assetsValue"]) == (
            Decimal(portfolio_summary["cashValue"]) + Decimal(portfolio_summary["investmentValue"])
        )
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_account_local_100_100_and_dashboard_global_60_40() -> None:
    prefix = single_support._prefix("5l-audit-allocation")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        await multi_support._set_single_position(
            f"{prefix}-a",
            snapshot_id=snapshots[0],
            value="60",
            cost="50",
        )
        await multi_support._set_single_position(
            f"{prefix}-b",
            snapshot_id=snapshots[1],
            value="40",
            cost="30",
        )

        portfolio = _portfolio_call(user_id, accounts)
        dashboard = _dashboard_call(user_id, accounts)

        assert portfolio.status_code == dashboard.status_code == 200
        local = [
            Decimal(account["positions"][0]["allocationPct"])
            for account in portfolio.json()["accounts"]
        ]
        global_values = [
            Decimal(position["allocationPct"]) for position in dashboard.json()["topPositions"]
        ]
        assert local == [Decimal("100"), Decimal("100")]
        assert global_values == [Decimal("60"), Decimal("40")]
    finally:
        await single_support._cleanup(prefix)


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
async def test_every_read_role_can_use_all_snapshot_backed_endpoints(
    role: AccountMemberRole,
) -> None:
    prefix = single_support._prefix(f"5l-audit-role-{role.value}")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(
            prefix,
            role=role,
        )
        responses = (
            _single_call(account_id, user_id),
            _portfolio_call(user_id, (account_id,), snapshot_ids=(snapshot_id,)),
            _dashboard_call(user_id, (account_id,), snapshot_ids=(snapshot_id,)),
        )
        assert [response.status_code for response in responses] == [200, 200, 200]
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign", "missing", "archived"])
async def test_access_failures_are_nondisclosing_and_return_no_partial_result(
    failure: str,
) -> None:
    prefix = single_support._prefix(f"5l-audit-access-{failure}")
    await single_support._cleanup(prefix)
    try:
        user_id, valid_account, _ = await single_support._seed(f"{prefix}-valid")
        if failure == "foreign":
            _, failing_account, _ = await single_support._seed(f"{prefix}-foreign")
        elif failure == "archived":
            _, failing_account, _ = await single_support._seed(
                f"{prefix}-archived",
                archived=True,
            )
            await multi_support._add_access(
                prefix,
                user_id=user_id,
                account_id=failing_account,
            )
        else:
            failing_account = f"{prefix}-missing-account"

        response = _portfolio_call(user_id, (valid_account, failing_account))

        _error_contract(
            response,
            404,
            "account_not_found",
            "The account was not found.",
        )
        assert "accounts" not in response.json()
        assert valid_account not in response.text
        assert failing_account not in response.text
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_exact_snapshot_guard_matches_and_wrong_guard_fails_generic() -> None:
    prefix = single_support._prefix("5l-audit-guard")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(prefix)
        exact = _portfolio_call(
            user_id,
            (account_id,),
            snapshot_ids=(snapshot_id,),
        )
        wrong = _portfolio_call(
            user_id,
            (account_id,),
            snapshot_ids=(f"{prefix}-wrong-snapshot",),
        )

        assert exact.status_code == 200
        _error_contract(
            wrong,
            409,
            "portfolio_snapshot_unavailable",
            "The requested portfolio snapshot is unavailable.",
        )
        assert account_id not in wrong.text
        assert snapshot_id not in wrong.text
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": "2032-08-03T00:00:00.000"},
        {"granularity": "hour"},
        {"currency": "USD"},
        {"calculationVersion": 2},
    ],
)
async def test_exact_metadata_mismatch_never_falls_back(
    changes: dict[str, object],
) -> None:
    prefix = single_support._prefix("5l-audit-metadata")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, _ = await single_support._seed(prefix)
        body = multi_support._body((account_id,))
        body.update(changes)
        response = multi_support._call(PORTFOLIO_PATH, user_id, body)

        _error_contract(
            response,
            409,
            "portfolio_snapshot_unavailable",
            "The requested portfolio snapshot is unavailable.",
        )
        assert account_id not in response.text
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_duplicate_account_and_snapshot_selectors_fail_before_partial_read() -> None:
    prefix = single_support._prefix("5l-audit-duplicate-selector")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        duplicate_account = _portfolio_call(
            user_id,
            (accounts[0], accounts[0]),
        )
        duplicate_snapshot = _portfolio_call(
            user_id,
            accounts,
            snapshot_ids=(snapshots[0], snapshots[0]),
        )

        for response in (duplicate_account, duplicate_snapshot):
            _error_contract(
                response,
                409,
                "portfolio_snapshot_unavailable",
                "The requested portfolio snapshot is unavailable.",
            )
            assert "accounts" not in response.json()
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_empty_account_set_is_rejected_syntactically() -> None:
    prefix = single_support._prefix("5l-audit-empty-selector")
    await single_support._cleanup(prefix)
    try:
        user_id, _, _ = await single_support._seed(prefix)
        response = multi_support._call(
            PORTFOLIO_PATH,
            user_id,
            multi_support._body((), snapshot_ids=()),
        )
        assert response.status_code == 422
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
async def test_unsupported_account_types_fail_closed(
    account_type: AccountType,
) -> None:
    prefix = single_support._prefix(f"5l-audit-unsupported-{account_type.value}")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, _ = await single_support._seed(
            prefix,
            account_type=account_type,
        )
        response = _portfolio_call(user_id, (account_id,))
        _error_contract(
            response,
            409,
            "portfolio_snapshot_unavailable",
            "The requested portfolio snapshot is unavailable.",
        )
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_corrupt_snapshot_item_and_graph_all_return_same_generic_409() -> None:
    prefixes = tuple(
        single_support._prefix(f"5l-audit-corrupt-{kind}") for kind in ("snapshot", "item", "graph")
    )
    for prefix in prefixes:
        await single_support._cleanup(prefix)
    try:
        responses = []
        for prefix, kind in zip(prefixes, ("snapshot", "item", "graph"), strict=True):
            user_id, account_id, snapshot_id = await single_support._seed(prefix)
            engine = single_support._engine()
            async with AsyncSession(engine) as session:
                if kind == "snapshot":
                    await session.execute(
                        update(AccountSnapshotModel)
                        .where(AccountSnapshotModel.id == snapshot_id)
                        .values(total_value=Decimal("999.000000"))
                    )
                elif kind == "item":
                    await session.execute(
                        update(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
                        .values(price_timestamp=SNAPSHOT_AT.replace(day=3))
                    )
                else:
                    await session.execute(
                        update(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.id == f"{prefix}-item-a")
                        .values(asset_id=f"{prefix}-asset-b")
                    )
                await session.commit()
            await engine.dispose()
            response = _portfolio_call(user_id, (account_id,))
            responses.append(response)
            assert account_id not in response.text
            assert snapshot_id not in response.text

        contracts = [
            (
                response.status_code,
                response.json()["error"]["code"],
                response.json()["error"]["message"],
            )
            for response in responses
        ]
        assert (
            contracts
            == [
                (
                    409,
                    "portfolio_snapshot_unavailable",
                    "The requested portfolio snapshot is unavailable.",
                )
            ]
            * 3
        )
    finally:
        for prefix in prefixes:
            await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_known_sql_read_failure_returns_generic_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = single_support._prefix("5l-audit-sql-error")
    await single_support._cleanup(prefix)

    async def fail_load(
        _repository: PortfolioSnapshotRepository,
        _account_id: str,
    ) -> None:
        raise SQLAlchemyError("sensitive internal sql detail")

    monkeypatch.setattr(PortfolioSnapshotRepository, "load_account", fail_load)
    try:
        user_id, account_id, _ = await single_support._seed(prefix)
        response = _portfolio_call(user_id, (account_id,))

        _error_contract(
            response,
            409,
            "portfolio_snapshot_unavailable",
            "The requested portfolio snapshot is unavailable.",
        )
        assert "sensitive" not in response.text
        assert account_id not in response.text
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_unique_constraint_and_duplicate_query_result_are_both_proven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = single_support._prefix("5l-audit-duplicate-candidate")
    await single_support._cleanup(prefix)
    original = PortfolioSnapshotRepository.load_exact_snapshots
    try:
        user_id, account_id, snapshot_id = await single_support._seed(prefix)
        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            existing = await session.get(AccountSnapshotModel, snapshot_id)
            assert existing is not None
            values = {
                column.name: getattr(
                    existing,
                    inspect(AccountSnapshotModel).get_property_by_column(column).key,
                )
                for column in AccountSnapshotModel.__table__.columns
            }
            values["id"] = f"{prefix}-duplicate"
            with pytest.raises(IntegrityError):
                await session.execute(insert(AccountSnapshotModel).values(**values))
                await session.flush()
            await session.rollback()
        await engine.dispose()

        async def duplicate_real_rows(
            repository: PortfolioSnapshotRepository,
            **kwargs: Any,
        ) -> tuple[AccountSnapshotModel, ...]:
            rows = await original(repository, **kwargs)
            assert len(rows) == 1
            return rows + rows

        monkeypatch.setattr(
            PortfolioSnapshotRepository,
            "load_exact_snapshots",
            duplicate_real_rows,
        )
        response = _portfolio_call(user_id, (account_id,))
        _error_contract(
            response,
            409,
            "portfolio_snapshot_unavailable",
            "The requested portfolio snapshot is unavailable.",
        )
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_every_snapshot_endpoint_is_one_read_only_repeatable_read_transaction(
    path: str,
) -> None:
    prefix = single_support._prefix(f"5l-audit-transaction-{_path_label(path)}")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        before = await _persisted_counts(prefix)
        sql: list[tuple[str, int]] = []
        session_states: list[bool] = []
        if path == "single":
            response = _single_call(
                accounts[0],
                user_id,
                sql=sql,
                session_states=session_states,
            )
            account_count = 1
        else:
            response = multi_support._call(
                path,
                user_id,
                multi_support._body(accounts, snapshot_ids=snapshots),
                sql=sql,
                session_states=session_states,
            )
            account_count = 2

        assert response.status_code == 200
        _assert_transaction_evidence(sql, account_count=account_count)
        assert session_states == [False]
        assert await _persisted_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_repeated_requests_are_byte_identical_and_do_not_change_data(
    path: str,
) -> None:
    prefix = single_support._prefix(f"5l-audit-repeat-{_path_label(path)}")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        before = await _persisted_counts(prefix)
        if path == "single":
            first = _single_call(accounts[0], user_id)
            second = _single_call(accounts[0], user_id)
        else:
            body = multi_support._body(accounts, snapshot_ids=snapshots)
            first = multi_support._call(path, user_id, body)
            second = multi_support._call(path, user_id, body)

        assert first.status_code == second.status_code == 200
        assert first.content == second.content
        assert await _persisted_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_account_selector_permutation_is_byte_identical(path: str) -> None:
    prefix = single_support._prefix(f"5l-audit-permutation-{path.split('/')[-2]}")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        first = multi_support._call(
            path,
            user_id,
            multi_support._body(accounts, snapshot_ids=snapshots),
        )
        second = multi_support._call(
            path,
            user_id,
            multi_support._body(
                tuple(reversed(accounts)),
                snapshot_ids=tuple(reversed(snapshots)),
            ),
        )
        assert first.status_code == second.status_code == 200
        assert first.content == second.content
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_same_asset_in_two_accounts_remains_two_account_scoped_positions() -> None:
    prefix = single_support._prefix("5l-audit-shared-asset")
    await single_support._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            first = await session.get(AccountSnapshotItemModel, f"{prefix}-a-item-a")
            second = await session.get(AccountSnapshotItemModel, f"{prefix}-b-item-a")
            assert first is not None and second is not None
            shared_listing_id = first.listing_id
            second.asset_id = first.asset_id
            second.listing_id = shared_listing_id
            second.symbol = first.symbol
            await session.commit()
        await engine.dispose()

        portfolio = _portfolio_call(user_id, accounts, snapshot_ids=snapshots)
        dashboard = _dashboard_call(user_id, accounts, snapshot_ids=snapshots)
        assert portfolio.status_code == dashboard.status_code == 200
        portfolio_positions = [
            position
            for account in portfolio.json()["accounts"]
            for position in account["positions"]
            if position["listingId"] == shared_listing_id
        ]
        dashboard_positions = [
            position
            for position in dashboard.json()["topPositions"]
            if position["listingId"] == shared_listing_id
        ]
        assert len(portfolio_positions) == len(dashboard_positions) == 2
        assert {position["accountId"] for position in dashboard_positions} == set(accounts)
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_repeatable_read_prevents_mixed_metadata_during_concurrent_commit(
    path: str,
) -> None:
    prefix = single_support._prefix(f"5l-audit-coherence-{path.split('/')[-2]}")
    await single_support._cleanup(prefix)
    reached = threading.Event()
    resume = threading.Event()
    try:
        user_id, accounts, snapshots = await multi_support._seed_pair(prefix)
        original_name = f"{prefix}-b account"
        task = asyncio.create_task(
            asyncio.to_thread(
                multi_support._call,
                path,
                user_id,
                multi_support._body(accounts, snapshot_ids=snapshots),
                pause_after_first_access=(reached, resume),
            )
        )
        assert await asyncio.to_thread(reached.wait, 10)

        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountModel)
                .where(AccountModel.id == accounts[1])
                .values(name="committed newer metadata")
            )
            await session.commit()
        await engine.dispose()
        resume.set()
        original = await asyncio.wait_for(task, timeout=15)

        assert original.status_code == 200
        assert original_name in _account_names(original.json(), path)
        assert "committed newer metadata" not in _account_names(original.json(), path)

        newer = multi_support._call(
            path,
            user_id,
            multi_support._body(accounts, snapshot_ids=snapshots),
        )
        assert newer.status_code == 200
        assert "committed newer metadata" in _account_names(newer.json(), path)
        assert original_name not in _account_names(newer.json(), path)
    finally:
        resume.set()
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_public_serialization_and_leakage_contract(path: str) -> None:
    prefix = single_support._prefix(f"5l-audit-public-{_path_label(path)}")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await single_support._seed(prefix)
        if path == "single":
            response = _single_call(account_id, user_id)
        else:
            response = multi_support._call(
                path,
                user_id,
                multi_support._body(
                    (account_id,),
                    snapshot_ids=(snapshot_id,),
                ),
            )

        assert response.status_code == 200
        payload = response.json()
        _assert_public_json(payload, dashboard=path == DASHBOARD_PATH)
        assert payload["timestamp"].endswith(".000")
        assert "+" not in payload["timestamp"] and not payload["timestamp"].endswith("Z")
        if path != DASHBOARD_PATH:
            positions = (
                payload["positions"] if path == "single" else payload["accounts"][0]["positions"]
            )
            assert positions[0]["priceTimestamp"].endswith(".000")
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_legacy_live_portfolio_endpoint_remains_registered_but_separate() -> None:
    prefix = single_support._prefix("5l-audit-legacy")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, _ = await single_support._seed(prefix)
        app = create_app(single_support._settings())
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/portfolio",
                params={"account_id": account_id},
                headers=single_support._headers(user_id),
            )

        assert response.status_code == 200
        assert "snapshotId" not in response.text
        assert "total_cost" in response.json()
    finally:
        await single_support._cleanup(prefix)
