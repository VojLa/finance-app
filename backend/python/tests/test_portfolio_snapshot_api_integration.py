from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.enums import (
    SnapshotGranularity as DbSnapshotGranularity,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = datetime(2032, 8, 2)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)
SECRET = "portfolio-snapshot-integration-secret-value"


def _prefix(label: str) -> str:
    return f"5lc-{uuid4().hex}-{label}"


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: str) -> str:
    now = int(time.time())
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 600,
            "jti": f"{user_id}-session",
        }
    )
    signed = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), signed.encode(), hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{signed}.{signature.decode()}"


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret=SECRET,
        _env_file=None,
    )


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _params(**changes: str) -> dict[str, str]:
    result = {
        "timestamp": "2032-08-02T00:00:00.000",
        "granularity": "day",
        "currency": "EUR",
        "calculationVersion": "1",
    }
    result.update(changes)
    return result


def _path(account_id: str) -> str:
    return f"/api/v1/portfolio/accounts/{account_id}/snapshot"


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        account_ids = tuple(
            await session.scalars(
                select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            )
        )
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
            await session.execute(
                delete(AccountSnapshotCanonicalBoundaryModel).where(
                    AccountSnapshotCanonicalBoundaryModel.snapshot_id.in_(snapshot_ids)
                )
            )
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.id.in_(snapshot_ids))
            )
        if account_ids:
            await session.execute(
                delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(LiabilityBalanceModel).where(
                    LiabilityBalanceModel.account_id.in_(account_ids)
                )
            )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.user_id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-")))
        if account_ids:
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(
            delete(SnapshotGenerationTargetModel).where(
                SnapshotGenerationTargetModel.generation_id.startswith(f"{prefix}-")
            )
        )
        await session.execute(
            delete(SnapshotGenerationModel).where(
                SnapshotGenerationModel.id.startswith(f"{prefix}-")
            )
        )
        await session.execute(delete(UserModel).where(UserModel.id.startswith(f"{prefix}-")))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    role: AccountMemberRole = AccountMemberRole.owner,
    account_type: AccountType = AccountType.broker,
    archived: bool = False,
    empty: bool = False,
    with_items: bool = True,
) -> tuple[str, str, str]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    snapshot_id = f"{prefix}-snapshot"
    generation_id = f"{prefix}-generation"
    liability = account_type in {AccountType.loan, AccountType.mortgage}
    credit_card = account_type is AccountType.credit_card
    if liability or credit_card or empty:
        with_items = False
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name=user_id,
                password_hash=None,
                base_currency="CZK",
                created_at=SNAPSHOT_AT,
                updated_at=SNAPSHOT_AT,
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name=f"{prefix} account",
                type=account_type,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=archived,
                archived_at=CREATED_AT if archived else None,
                created_at=SNAPSHOT_AT,
                updated_at=SNAPSHOT_AT,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-member",
                account_id=account_id,
                user_id=user_id,
                role=role,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=SNAPSHOT_AT,
                created_at=SNAPSHOT_AT,
                updated_at=SNAPSHOT_AT,
            )
        )
        session.add(
            SnapshotGenerationModel(
                id=generation_id,
                state="published",
                created_at=CREATED_AT,
                published_at=CREATED_AT,
            )
        )
        await session.flush()
        session.add(
            SnapshotGenerationTargetModel(
                generation_id=generation_id,
                user_id=user_id,
                created_at=CREATED_AT,
                staged_by_job_id=None,
                staged_lease_version=None,
                staged_lease_owner=None,
            )
        )
        if credit_card:
            session.add(
                TransactionModel(
                    id=f"{prefix}-purchase",
                    account_id=account_id,
                    date=SNAPSHOT_AT,
                    booking_date=SNAPSHOT_AT,
                    amount=Decimal("-25.000000"),
                    currency="EUR",
                    type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    description="card purchase",
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
        elif liability:
            session.add(
                LiabilityBalanceModel(
                    id=f"{prefix}-balance",
                    account_id=account_id,
                    effective_at=SNAPSHOT_AT,
                    currency="EUR",
                    outstanding_principal=Decimal("25.000000"),
                    accrued_interest=Decimal("0.000000"),
                    fees_outstanding=Decimal("0.000000"),
                    total_outstanding=Decimal("25.000000"),
                    source=LiabilityBalanceSource.manual,
                    external_id=None,
                    created_at=CREATED_AT,
                )
            )
        await session.flush()
        canonical_state = await session.get(AccountCanonicalStateModel, account_id)
        assert canonical_state is not None
        canonical_revision = canonical_state.last_revision
        if with_items:
            canonical_state.holding_revision = canonical_state.last_investment_revision
        investment = Decimal("100.000000") if with_items else Decimal("0.000000")
        cost_basis = Decimal("80.000000") if with_items else Decimal("0.000000")
        cash = (
            Decimal("-25.000000")
            if credit_card
            else (Decimal("0.000000") if liability else Decimal("10.000000"))
        )
        liabilities = Decimal("25.000000") if liability else Decimal("0.000000")
        snapshot = AccountSnapshotModel(
            id=snapshot_id,
            account_id=account_id,
            generation_id=generation_id,
            timestamp=SNAPSHOT_AT,
            granularity=DbSnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            currency="EUR",
            cash_value=cash,
            investment_value=investment,
            investment_cost_basis=cost_basis,
            liabilities_value=liabilities,
            total_value=cash + investment - liabilities,
            is_recalculated=True,
            calculated_at=CREATED_AT,
            calculation_version=1,
            created_at=CREATED_AT,
            net_deposits_value=Decimal("0.000000"),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=investment - cost_basis,
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            cash_value_by_currency={"EUR": format(cash, ".6f")},
            investment_value_by_currency=None,
            investment_cost_basis_by_currency=None,
            net_deposits_by_currency={},
            realized_pnl_by_currency=None,
            unrealized_pnl_by_currency=None,
            fees_by_currency=None,
            taxes_by_currency=None,
            exchange_rates=None,
        )
        session.add(snapshot)
        await session.flush()
        session.add(
            AccountSnapshotCanonicalBoundaryModel(
                snapshot_id=snapshot_id,
                account_id=account_id,
                canonical_revision=canonical_revision,
                investment_revision=0 if with_items else None,
                holding_revision=0 if with_items else None,
                selected_liability_balance_id=f"{prefix}-balance" if liability else None,
                created_at=CREATED_AT,
            )
        )
        if with_items:
            for suffix, symbol, native_currency, value, cost, allocation in (
                ("a", "AAA", "USD", "60.000000", "50.0000000000", "60.0000"),
                ("b", "BBB", "GBP", "40.000000", "30.0000000000", "40.0000"),
            ):
                asset = AssetModel(
                    id=f"{prefix}-asset-{suffix}",
                    symbol=symbol,
                    isin=None,
                    name=f"{symbol} asset",
                    asset_type=AssetType.stock,
                    currency=native_currency,
                    created_at=SNAPSHOT_AT,
                    updated_at=SNAPSHOT_AT,
                )
                listing = AssetListingModel(
                    id=f"{prefix}-listing-{suffix}",
                    asset_id=asset.id,
                    symbol=symbol,
                    exchange=None,
                    mic=None,
                    currency=native_currency,
                    country=None,
                    provider=PriceSource.manual,
                    provider_symbol=None,
                    is_primary=True,
                    created_at=SNAPSHOT_AT,
                    updated_at=SNAPSHOT_AT,
                )
                session.add(asset)
                await session.flush()
                session.add(listing)
                await session.flush()
                session.add(
                    AccountSnapshotItemModel(
                        id=f"{prefix}-item-{suffix}",
                        snapshot_id=snapshot_id,
                        asset_id=asset.id,
                        listing_id=listing.id,
                        symbol=symbol,
                        quantity=Decimal("2.0000000000"),
                        price_per_unit=Decimal(value) / Decimal(2),
                        price_currency=native_currency,
                        price_source=PriceSource.manual,
                        price_timestamp=SNAPSHOT_AT,
                        value=Decimal(value),
                        cost_basis=Decimal(cost),
                        cost_currency="EUR",
                        allocation_pct=Decimal(allocation),
                        created_at=CREATED_AT,
                        native_value=Decimal(value),
                        value_currency=native_currency,
                        native_cost_basis=Decimal(cost),
                        native_cost_currency=native_currency,
                        native_cost_basis_by_currency={native_currency: cost},
                        average_buy_price=Decimal(cost) / Decimal(2),
                        average_buy_price_currency=native_currency,
                    )
                )
        await session.commit()
    await engine.dispose()
    return user_id, account_id, snapshot_id


async def _add_user(prefix: str, suffix: str = "foreign") -> str:
    user_id = f"{prefix}-{suffix}"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name=user_id,
                password_hash=None,
                base_currency="CZK",
                created_at=SNAPSHOT_AT,
                updated_at=SNAPSHOT_AT,
            )
        )
        await session.commit()
    await engine.dispose()
    return user_id


def _call(
    account_id: str,
    user_id: str,
    *,
    params: dict[str, str] | None = None,
    sql: list[tuple[str, int]] | None = None,
):
    app = create_app(_settings())
    with TestClient(app) as client:
        if sql is not None:
            database = app.state.database

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
            _path(account_id),
            params=params or _params(),
            headers=_headers(user_id),
        )


async def _counts(account_id: str) -> tuple[int, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        snapshots = (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
        items = (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotItemModel)
                .join(
                    AccountSnapshotModel,
                    AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
                )
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
    await engine.dispose()
    return snapshots, items


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_type", "expected_cash", "expected_liabilities"),
    [
        (AccountType.broker, Decimal("10"), Decimal("0")),
        (AccountType.credit_card, Decimal("-25"), Decimal("0")),
        (AccountType.loan, Decimal("0"), Decimal("25")),
    ],
)
async def test_fixture_has_published_canonical_and_liability_evidence(
    account_type: AccountType,
    expected_cash: Decimal,
    expected_liabilities: Decimal,
) -> None:
    prefix = _prefix(f"lineage-{account_type.value}")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix, account_type=account_type)
        engine = _engine()
        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, snapshot_id)
            generation = await session.get(SnapshotGenerationModel, f"{prefix}-generation")
            target = await session.get(
                SnapshotGenerationTargetModel, (f"{prefix}-generation", user_id)
            )
            state = await session.get(AccountCanonicalStateModel, account_id)
            boundary = await session.get(AccountSnapshotCanonicalBoundaryModel, snapshot_id)
            transactions = tuple(
                await session.scalars(
                    select(TransactionModel).where(TransactionModel.account_id == account_id)
                )
            )
            balances = tuple(
                await session.scalars(
                    select(LiabilityBalanceModel).where(
                        LiabilityBalanceModel.account_id == account_id
                    )
                )
            )
            assert snapshot is not None and generation is not None and target is not None
            assert state is not None and boundary is not None
            assert snapshot.generation_id == generation.id
            assert generation.state == "published" and generation.published_at == CREATED_AT
            assert boundary.account_id == account_id
            assert boundary.canonical_revision == state.last_revision
            assert snapshot.cash_value == expected_cash
            assert snapshot.liabilities_value == expected_liabilities
            if account_type is AccountType.credit_card:
                assert len(transactions) == 1 and transactions[0].amount == Decimal("-25")
                assert not balances and boundary.selected_liability_balance_id is None
            elif account_type is AccountType.loan:
                assert not transactions and len(balances) == 1
                assert balances[0].total_outstanding == Decimal("25")
                assert boundary.selected_liability_balance_id == balances[0].id
            else:
                assert not transactions and not balances
                assert boundary.selected_liability_balance_id is None
        await engine.dispose()

        response = _call(account_id, user_id)
        assert response.status_code == 200
        assert response.json()["summary"]["cashValue"] == f"{expected_cash:.6f}"
        assert response.json()["summary"]["liabilitiesValue"] == f"{expected_liabilities:.6f}"
    finally:
        await _cleanup(prefix)


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
async def test_every_current_read_role_gets_exact_broker_snapshot(
    role: AccountMemberRole,
) -> None:
    prefix = _prefix(role.value)
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix, role=role)

        response = _call(
            account_id,
            user_id,
            params=_params(snapshotId=snapshot_id),
        )

        assert response.status_code == 200
        assert response.json()["snapshotId"] == snapshot_id
        assert response.json()["account"]["accountId"] == account_id
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_exact_response_preserves_currency_contract_and_leaks_no_audit() -> None:
    prefix = _prefix("exact")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(prefix)
        before = await _counts(account_id)
        sql: list[tuple[str, int]] = []

        first = _call(account_id, user_id, sql=sql)
        second = _call(account_id, user_id)
        after = await _counts(account_id)

        assert first.status_code == 200
        assert first.json() == second.json()
        payload = first.json()
        assert [position["nativeValueCurrency"] for position in payload["positions"]] == [
            "USD",
            "GBP",
        ]
        assert {position["valueCurrency"] for position in payload["positions"]} == {"EUR"}
        assert {position["costCurrency"] for position in payload["positions"]} == {"EUR"}
        assert payload["summary"]["cashByCurrency"] == [{"currency": "EUR", "amount": "10.000000"}]
        assert payload["summary"]["netDepositsByCurrency"] == []
        assert payload["timestamp"].endswith(".000")
        assert all(position["priceTimestamp"].endswith(".000") for position in payload["positions"])
        assert before == after == (1, 2)

        forbidden = {
            "userId",
            "membershipId",
            "role",
            "relationType",
            "selectedItemIds",
            "selectedSnapshotId",
            "priceId",
            "priceSource",
            "exchangeRateId",
            "exchangeRates",
            "historicalRateIds",
            "snapshotRates",
            "investmentValueByCurrency",
            "investmentCostBasisByCurrency",
            "realizedPnlByCurrency",
            "unrealizedPnlByCurrency",
            "feesByCurrency",
            "taxesByCurrency",
            "calculatedAt",
            "createdAt",
        }

        def audit(value: object) -> None:
            if isinstance(value, dict):
                assert forbidden.isdisjoint(value)
                for child in value.values():
                    audit(child)
            elif isinstance(value, list):
                for child in value:
                    audit(child)
            else:
                assert not isinstance(value, float)

        audit(payload)

        statements = [statement for statement, _ in sql]
        normalized = [" ".join(statement.lower().split()) for statement in statements]
        set_index = normalized.index("set transaction isolation level repeatable read")
        access_index = next(
            index
            for index, statement in enumerate(normalized)
            if "accountmember" in statement and index > set_index
        )
        reader_indices = [
            index
            for index, statement in enumerate(normalized)
            if index > access_index
            and any(
                table in statement
                for table in (
                    "accountsnapshot",
                    "accountsnapshotitem",
                    "assetlisting",
                )
            )
        ]
        assert set_index > 0
        assert access_index > set_index
        assert reader_indices
        coherent_transaction = sql[set_index][1]
        assert sql[access_index][1] == coherent_transaction
        assert all(sql[index][1] == coherent_transaction for index in reader_indices)
        assert all(
            not statement.lstrip().lower().startswith(("insert ", "update ", "delete "))
            for statement in statements
        )
        assert all("for update" not in statement.lower() for statement in statements)
        assert all("advisory" not in statement.lower() for statement in statements)
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_type", "empty", "total"),
    [
        (AccountType.loan, False, "-25.000000"),
        (AccountType.broker, True, "10.000000"),
    ],
)
async def test_summary_only_and_empty_investment_shapes(
    account_type: AccountType,
    empty: bool,
    total: str,
) -> None:
    prefix = _prefix(f"{account_type.value}-{empty}")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(
            prefix,
            account_type=account_type,
            empty=empty,
        )

        response = _call(account_id, user_id)

        assert response.status_code == 200
        assert response.json()["positions"] == []
        assert response.json()["summary"]["positionCount"] == 0
        assert response.json()["summary"]["totalValue"] == total
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"snapshotId": "wrong-snapshot"},
        {"timestamp": "2032-08-03T00:00:00.000"},
        {"currency": "USD"},
        {"granularity": "hour"},
        {"calculationVersion": "2"},
    ],
)
async def test_exact_selectors_never_fall_back(changes: dict[str, str]) -> None:
    prefix = _prefix("selector")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(prefix)

        response = _call(account_id, user_id, params=_params(**changes))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert response.json()["error"]["message"] == (
            "The requested portfolio snapshot is unavailable."
        )
        assert account_id not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    ["aggregate", "future-price", "missing-breakdown", "malformed-breakdown"],
)
async def test_corrupt_persisted_evidence_returns_generic_409(corruption: str) -> None:
    prefix = _prefix(corruption)
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            if corruption == "aggregate":
                await session.execute(
                    update(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id == snapshot_id)
                    .values(total_value=Decimal("999.000000"))
                )
            elif corruption == "future-price":
                await session.execute(
                    update(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
                    .values(price_timestamp=SNAPSHOT_AT + timedelta(days=1))
                )
            elif corruption == "missing-breakdown":
                await session.execute(
                    update(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id == snapshot_id)
                    .values(cash_value_by_currency=None)
                )
            else:
                await session.execute(
                    update(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id == snapshot_id)
                    .values(cash_value_by_currency={"EUR": "10.0"})
                )
            await session.commit()
        await engine.dispose()

        response = _call(account_id, user_id)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert account_id not in response.text
        assert snapshot_id not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_foreign_missing_and_archived_accounts_share_not_found_contract() -> None:
    prefix = _prefix("hidden")
    await _cleanup(prefix)
    try:
        owner_id, account_id, _ = await _seed(prefix)
        foreign_id = await _add_user(prefix)
        foreign = _call(account_id, foreign_id)
        missing = _call(f"{prefix}-missing-account", owner_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountModel)
                .where(AccountModel.id == account_id)
                .values(is_archived=True, archived_at=CREATED_AT)
            )
            await session.commit()
        await engine.dispose()
        archived = _call(account_id, owner_id)

        contracts = [
            (
                response.status_code,
                response.json()["error"]["code"],
                response.json()["error"]["message"],
            )
            for response in (foreign, missing, archived)
        ]
        assert contracts == [(404, "account_not_found", "The account was not found.")] * 3
        assert account_id not in foreign.text
        assert owner_id not in foreign.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_concurrent_gets_are_equal_and_legacy_portfolio_still_works() -> None:
    prefix = _prefix("concurrent")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(prefix)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = tuple(
                executor.map(
                    lambda _value: _call(account_id, user_id),
                    range(2),
                )
            )

        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json() == responses[1].json()

        app = create_app(_settings())
        with TestClient(app) as client:
            legacy = client.get(
                "/api/v1/portfolio",
                params={"account_id": account_id},
                headers=_headers(user_id),
            )
        assert legacy.status_code == 200
    finally:
        await _cleanup(prefix)
