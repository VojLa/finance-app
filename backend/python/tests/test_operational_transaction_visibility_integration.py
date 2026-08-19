from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.budgets import (
    BudgetAccountModel,
    BudgetItemCategoryModel,
    BudgetItemModel,
    BudgetModel,
)
from app.db.models.categories import CategoryModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    BudgetPeriodType,
    CategoryType,
    ExchangeRateSource,
    ImportSource,
    ImportStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import (
    TransactionModel,
    TransactionPairModel,
    TransactionReportingEvidenceModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.budgets.service import month_range
from app.modules.operational_dashboard.service import OperationalDashboardService
from app.modules.transactions.service import TransactionService

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]

_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "database"
    / "revisions"
    / "3p0001rbfoundation"
    / "schema.sql"
)
_NOW = datetime(2026, 8, 20, 12)
_USER_ID = "visibility-user"
_ACCOUNT_ID = "visibility-account"
_CATEGORY_ID = "visibility-food"


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


async def _create_database() -> tuple[asyncpg.Connection, str, str]:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_visibility_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    target = await asyncpg.connect(
        target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    try:
        await target.execute(
            _SCHEMA.read_text(encoding="utf-8").replace('CREATE SCHEMA "public";\n', "", 1)
        )
    finally:
        await target.close()
    return admin, database_name, target_url.render_as_string(hide_password=False)


async def _drop_database(admin: asyncpg.Connection, database_name: str) -> None:
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await admin.close()


def _job(*, job_id: str, status: BackgroundJobStatus) -> BackgroundJobModel:
    completed = status is BackgroundJobStatus.completed
    failed = status is BackgroundJobStatus.failed
    running = status is BackgroundJobStatus.running
    return BackgroundJobModel(
        id=job_id,
        user_id=_USER_ID,
        account_id=_ACCOUNT_ID,
        kind=BackgroundJobKind.import_workflow,
        status=status,
        idempotency_key=f"{job_id}-idempotency",
        payload={"batch_ids": [f"{job_id}-batch"]},
        checkpoint={},
        progress={},
        result={"completed": True} if completed else None,
        error_code="import_failed" if failed else None,
        error_message="Safe failure." if failed else None,
        attempt_count=1,
        manual_retry_count=0,
        max_attempts=3,
        run_after=_NOW,
        lease_owner="visibility-worker" if running else None,
        lease_version=1 if running else 0,
        lease_expires_at=_NOW + timedelta(minutes=5) if running else None,
        lease_heartbeat_at=_NOW if running else None,
        started_at=_NOW if (completed or failed or running) else None,
        finished_at=_NOW if (completed or failed) else None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _transaction(
    *,
    transaction_id: str,
    amount: Decimal,
    currency: str = "CZK",
    transaction_type: TransactionType,
    classification: TransactionClassification,
    batch_id: str | None,
    category_id: str | None = None,
    reporting_amount: Decimal | None = None,
) -> TransactionModel:
    return TransactionModel(
        id=transaction_id,
        date=_NOW,
        booking_date=None,
        amount=amount,
        currency=currency,
        reporting_amount=reporting_amount,
        reporting_currency="CZK" if reporting_amount is not None else None,
        type=transaction_type,
        classification=classification,
        description=transaction_id,
        note=None,
        counterparty=None,
        external_id=None,
        is_reviewed=True,
        archived_at=None,
        deleted_at=None,
        category_id=category_id,
        account_id=_ACCOUNT_ID,
        import_batch_id=batch_id,
        created_at=_NOW,
        updated_at=_NOW,
    )


async def _seed(database_url: str) -> None:
    engine = create_async_engine(normalize_database_url(database_url))
    current_start, current_end = month_range(_NOW.month, _NOW.year)
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                [
                    UserModel(
                        id=_USER_ID,
                        email="visibility@example.test",
                        name=None,
                        password_hash=None,
                        base_currency="CZK",
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                    AccountModel(
                        id=_ACCOUNT_ID,
                        name="Visibility account",
                        type=AccountType.bank,
                        currency="CZK",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AccountMemberModel(
                        id="visibility-member",
                        account_id=_ACCOUNT_ID,
                        user_id=_USER_ID,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=_NOW,
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                    CategoryModel(
                        id=_CATEGORY_ID,
                        name="Food",
                        icon=None,
                        color="#00aa00",
                        type=CategoryType.expense,
                        parent_id=None,
                        is_default=False,
                        user_id=_USER_ID,
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                ]
            )
            jobs = (
                ("queued", BackgroundJobStatus.queued),
                ("running", BackgroundJobStatus.running),
                ("failed", BackgroundJobStatus.failed),
                ("completed", BackgroundJobStatus.completed),
                ("foreign", BackgroundJobStatus.completed),
            )
            session.add_all([_job(job_id=job_id, status=status) for job_id, status in jobs])
            session.add_all(
                [
                    ImportBatchModel(
                        id=f"{job_id}-batch",
                        user_id=_USER_ID,
                        account_id=_ACCOUNT_ID,
                        source=ImportSource.raiffeisenbank,
                        filename=f"{job_id}.csv",
                        file_size=1,
                        file_encoding="utf-8",
                        checksum=f"{index:064x}",
                        status=ImportStatus.completed,
                        rows_total=1,
                        rows_imported=1,
                        rows_skipped=0,
                        created_at=_NOW,
                        completed_at=_NOW,
                        retain_until=None,
                        raw_data_purged_at=None,
                    )
                    for index, (job_id, _) in enumerate(jobs, start=1)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ImportJobBatchModel(
                        job_id=job_id,
                        batch_id=f"{job_id}-batch",
                        user_id=_USER_ID,
                        account_id=_ACCOUNT_ID,
                        created_at=_NOW,
                    )
                    for job_id, _ in jobs
                ]
            )
            session.add(
                ImportJobAffectedAccountModel(
                    job_id="completed",
                    account_id=_ACCOUNT_ID,
                    user_id=_USER_ID,
                    created_at=_NOW,
                )
            )
            transactions = [
                _transaction(
                    transaction_id="legacy-income",
                    amount=Decimal("10"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id=None,
                ),
                _transaction(
                    transaction_id="queued-income",
                    amount=Decimal("20"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="queued-batch",
                ),
                _transaction(
                    transaction_id="running-expense",
                    amount=Decimal("-30"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="running-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="failed-income",
                    amount=Decimal("35"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="failed-batch",
                ),
                _transaction(
                    transaction_id="completed-income",
                    amount=Decimal("40"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="eur-without-evidence",
                    amount=Decimal("-4"),
                    currency="EUR",
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                    reporting_amount=Decimal("-100"),
                ),
                _transaction(
                    transaction_id="eur-with-evidence",
                    amount=Decimal("-5"),
                    currency="EUR",
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                    reporting_amount=Decimal("-999"),
                ),
                _transaction(
                    transaction_id="eur-with-wrong-job",
                    amount=Decimal("-6"),
                    currency="EUR",
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                    reporting_amount=Decimal("-150"),
                ),
                _transaction(
                    transaction_id="published-pair-expense",
                    amount=Decimal("-50"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="published-pair-income",
                    amount=Decimal("50"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="unpublished-pair-expense",
                    amount=Decimal("-60"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="unpublished-pair-income",
                    amount=Decimal("60"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="ambiguous-pair",
                    amount=Decimal("-70"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="ambiguous-pair-left",
                    amount=Decimal("70"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="ambiguous-pair-right",
                    amount=Decimal("70"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="invalid-published-pair",
                    amount=Decimal("-80"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="invalid-published-pair-other",
                    amount=Decimal("80"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
                _transaction(
                    transaction_id="failed-published-pair",
                    amount=Decimal("-90"),
                    transaction_type=TransactionType.expense,
                    classification=TransactionClassification.real_expense,
                    batch_id="completed-batch",
                    category_id=_CATEGORY_ID,
                ),
                _transaction(
                    transaction_id="failed-published-pair-other",
                    amount=Decimal("90"),
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    batch_id="completed-batch",
                ),
            ]
            session.add_all(transactions)
            session.add(
                ExchangeRateModel(
                    id="visibility-eur-czk",
                    from_currency="EUR",
                    to_currency="CZK",
                    rate=Decimal("25"),
                    date=_NOW,
                    source=ExchangeRateSource.manual,
                    created_at=_NOW,
                )
            )
            session.add(
                TransactionReportingEvidenceModel(
                    transaction_id="eur-with-evidence",
                    source_amount=Decimal("-5"),
                    source_currency="EUR",
                    source_event_time=_NOW,
                    reporting_amount=Decimal("-125"),
                    reporting_currency="CZK",
                    exchange_rate_id="visibility-eur-czk",
                    calculation_version=1,
                    background_job_id="completed",
                    published_at=_NOW,
                    created_at=_NOW,
                )
            )
            session.add(
                TransactionReportingEvidenceModel(
                    transaction_id="eur-with-wrong-job",
                    source_amount=Decimal("-6"),
                    source_currency="EUR",
                    source_event_time=_NOW,
                    reporting_amount=Decimal("-150"),
                    reporting_currency="CZK",
                    exchange_rate_id="visibility-eur-czk",
                    calculation_version=1,
                    background_job_id="foreign",
                    published_at=_NOW,
                    created_at=_NOW,
                )
            )
            session.add_all(
                [
                    TransactionPairModel(
                        id="published-pair",
                        from_transaction_id="published-pair-expense",
                        to_transaction_id="published-pair-income",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="a" * 64,
                        background_job_id="completed",
                        published_at=_NOW,
                        created_at=_NOW,
                    ),
                    TransactionPairModel(
                        id="unpublished-pair",
                        from_transaction_id="unpublished-pair-expense",
                        to_transaction_id="unpublished-pair-income",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="b" * 64,
                        background_job_id="completed",
                        published_at=None,
                        created_at=_NOW,
                    ),
                    TransactionPairModel(
                        id="ambiguous-pair-one",
                        from_transaction_id="ambiguous-pair",
                        to_transaction_id="ambiguous-pair-left",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="c" * 64,
                        background_job_id="completed",
                        published_at=_NOW,
                        created_at=_NOW,
                    ),
                    TransactionPairModel(
                        id="ambiguous-pair-two",
                        from_transaction_id="ambiguous-pair-right",
                        to_transaction_id="ambiguous-pair",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="d" * 64,
                        background_job_id="completed",
                        published_at=_NOW,
                        created_at=_NOW,
                    ),
                    TransactionPairModel(
                        id="invalid-published-pair",
                        from_transaction_id="invalid-published-pair",
                        to_transaction_id="invalid-published-pair-other",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="e" * 64,
                        background_job_id="foreign",
                        published_at=_NOW,
                        created_at=_NOW,
                    ),
                    TransactionPairModel(
                        id="failed-published-pair",
                        from_transaction_id="failed-published-pair",
                        to_transaction_id="failed-published-pair-other",
                        classification=TransactionClassification.internal_transfer,
                        source=ImportSource.raiffeisenbank,
                        evidence_version=1,
                        evidence_hash="f" * 64,
                        background_job_id="failed",
                        published_at=_NOW,
                        created_at=_NOW,
                    ),
                    BudgetModel(
                        id="visibility-budget",
                        name="Monthly budget",
                        period_start=current_start,
                        period_end=current_end,
                        period_type=BudgetPeriodType.monthly,
                        currency="CZK",
                        rollover_enabled=False,
                        user_id=_USER_ID,
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    BudgetAccountModel(
                        id="visibility-budget-account",
                        budget_id="visibility-budget",
                        account_id=_ACCOUNT_ID,
                        created_at=_NOW,
                    ),
                    BudgetItemModel(
                        id="visibility-budget-item",
                        name=None,
                        amount=Decimal("1000"),
                        currency="CZK",
                        rollover_amount=Decimal(0),
                        budget_id="visibility-budget",
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                ]
            )
            await session.flush()
            session.add(
                BudgetItemCategoryModel(
                    id="visibility-budget-category",
                    budget_item_id="visibility-budget-item",
                    category_id=_CATEGORY_ID,
                    created_at=_NOW,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _assert_readers(database_url: str) -> None:
    principal = AuthenticatedPrincipal(
        user_id=_USER_ID,
        email="visibility@example.test",
        name=None,
    )
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine) as session:
            listed = await TransactionService(session).list_transactions(
                principal=principal,
                page=1,
                transaction_type=None,
                category_id=None,
                account_id=None,
                search=None,
            )
            assert listed.total == 9
            listed_types = {row.id: row.type.value for row in listed.transactions}
            assert set(listed_types) == {
                "legacy-income",
                "completed-income",
                "eur-with-evidence",
                "published-pair-expense",
                "published-pair-income",
                "unpublished-pair-expense",
                "unpublished-pair-income",
                "ambiguous-pair-left",
                "ambiguous-pair-right",
            }
            assert listed_types["published-pair-expense"] == "transfer"
            assert listed_types["published-pair-income"] == "transfer"
            assert listed_types["ambiguous-pair-left"] == "transfer"
            assert listed_types["ambiguous-pair-right"] == "transfer"
            assert "eur-without-evidence" not in listed_types
            assert "eur-with-wrong-job" not in listed_types
            assert "queued-income" not in listed_types
            assert "running-expense" not in listed_types
            assert "failed-income" not in listed_types
            assert "ambiguous-pair" not in listed_types
            assert "invalid-published-pair" not in listed_types
            assert "invalid-published-pair-other" not in listed_types
            assert "failed-published-pair" not in listed_types
            assert "failed-published-pair-other" not in listed_types

            expense_page = await TransactionService(session).list_transactions(
                principal=principal,
                page=1,
                transaction_type=TransactionType.expense,
                category_id=None,
                account_id=None,
                search=None,
            )
            assert {row.id for row in expense_page.transactions} == {
                "eur-with-evidence",
                "unpublished-pair-expense",
            }

            dashboard = await OperationalDashboardService(session).read(
                principal=principal,
                now=_NOW,
            )
            assert dashboard.summary.current_month_income_czk == Decimal("110.000000")
            assert dashboard.summary.current_month_expense_czk == Decimal("185.000000")
            assert dashboard.summary.current_month_net_czk == Decimal("-75.000000")
            assert dashboard.expense_by_category[0].amount_czk == Decimal("185.000000")
            assert dashboard.budget is not None
            assert dashboard.budget.spent_czk == Decimal("185.000000")
    finally:
        await engine.dispose()


async def _exercise() -> None:
    admin, database_name, database_url = await _create_database()
    try:
        await _seed(database_url)
        await _assert_readers(database_url)
    finally:
        await _drop_database(admin, database_name)


def test_operational_readers_fail_closed_until_canonical_publication() -> None:
    _run(_exercise())
