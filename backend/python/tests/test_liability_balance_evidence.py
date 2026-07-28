from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.modules.liabilities.evidence_service import (
    LiabilityBalanceEvidence,
    LiabilityBalanceEvidenceService,
    LiabilityBalanceEvidenceStateError,
    SelectLiabilityBalanceCommand,
)

NOW = datetime(2026, 7, 28, 10, 20)


def _account(
    *,
    account_type: AccountType = AccountType.credit_card,
    account_id: str = "account-a",
    currency: str = "CZK",
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=account_id,
        name="Liability",
        type=account_type,
        currency=currency,
        color=None,
        notes=None,
        is_archived=archived,
        archived_at=NOW if archived else None,
        created_at=NOW - timedelta(days=30),
        updated_at=NOW,
    )


def _balance(
    *,
    balance_id: str = "balance-a",
    account_id: str = "account-a",
    effective_at: datetime = NOW - timedelta(days=1),
    currency: str = "CZK",
    principal: object = Decimal("100"),
    interest: object = Decimal("2"),
    fees: object = Decimal("3"),
    total: object = Decimal("105"),
    source: object = LiabilityBalanceSource.statement,
    external_id: object = "statement-a",
    created_at: datetime = NOW,
) -> LiabilityBalanceModel:
    return LiabilityBalanceModel(
        id=balance_id,
        account_id=account_id,
        effective_at=effective_at,
        currency=currency,
        outstanding_principal=cast(Any, principal),
        accrued_interest=cast(Any, interest),
        fees_outstanding=cast(Any, fees),
        total_outstanding=cast(Any, total),
        source=cast(Any, source),
        external_id=cast(Any, external_id),
        created_at=created_at,
    )


class _Repository:
    def __init__(
        self,
        account: AccountModel | None,
        rows: tuple[LiabilityBalanceModel, ...],
    ) -> None:
        self.account = account
        self.rows = rows
        self.load_account_calls: list[str] = []
        self.load_balance_calls: list[tuple[str, datetime]] = []

    async def load_account(self, account_id: str) -> AccountModel | None:
        self.load_account_calls.append(account_id)
        return self.account

    async def load_eligible_balances(
        self,
        account_id: str,
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]:
        self.load_balance_calls.append((account_id, through))
        return self.rows


def _session() -> AsyncSession:
    return cast(AsyncSession, AsyncMock(spec=AsyncSession))


def test_liability_balance_model_has_exact_physical_contract() -> None:
    table = cast(Any, LiabilityBalanceModel.__table__)
    assert table.schema == "public"
    assert tuple(table.columns) == (
        table.c.id,
        table.c.accountId,
        table.c.effectiveAt,
        table.c.currency,
        table.c.outstandingPrincipal,
        table.c.accruedInterest,
        table.c.feesOutstanding,
        table.c.totalOutstanding,
        table.c.source,
        table.c.externalId,
        table.c.createdAt,
    )
    assert table.c.effectiveAt.type.precision == 3
    assert table.c.effectiveAt.type.timezone is False
    assert table.c.createdAt.type.precision == 3
    for name in (
        "outstandingPrincipal",
        "accruedInterest",
        "feesOutstanding",
        "totalOutstanding",
    ):
        assert table.c[name].type.precision == 18
        assert table.c[name].type.scale == 6
        assert table.c[name].nullable is False
    assert table.c.externalId.nullable is True

    constraint_names = {constraint.name for constraint in table.constraints}
    assert {
        "LiabilityBalance_pkey",
        "LiabilityBalance_accountId_effectiveAt_source_key",
        "LiabilityBalance_accountId_source_externalId_key",
        "LiabilityBalance_outstandingPrincipal_nonnegative",
        "LiabilityBalance_accruedInterest_nonnegative",
        "LiabilityBalance_feesOutstanding_nonnegative",
        "LiabilityBalance_totalOutstanding_nonnegative",
        "LiabilityBalance_totalOutstanding_components",
        "LiabilityBalance_accountId_fkey",
    } <= constraint_names
    assert (
        len(
            [
                constraint
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            ]
        )
        == 5
    )
    assert (
        len(
            [
                constraint
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            ]
        )
        == 2
    )
    foreign_key = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )
    assert foreign_key.onupdate == "CASCADE"
    assert foreign_key.ondelete == "CASCADE"
    index = next(index for index in table.indexes if isinstance(index, Index))
    assert index.name == "LiabilityBalance_accountId_effectiveAt_idx"
    assert tuple(column.name for column in index.columns) == ("accountId", "effectiveAt")


async def _select(
    *,
    account: AccountModel | None = None,
    rows: tuple[LiabilityBalanceModel, ...] | None = None,
    timestamp: datetime = NOW,
) -> tuple[LiabilityBalanceEvidence, AsyncSession, _Repository]:
    session = _session()
    repository = _Repository(account or _account(), rows or (_balance(),))
    result = await LiabilityBalanceEvidenceService(
        session,
        repository=repository,
    ).select(
        SelectLiabilityBalanceCommand(
            account_id="account-a",
            snapshot_timestamp=timestamp,
        )
    )
    return result, session, repository


@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
async def test_supported_liability_accounts_return_exact_immutable_evidence(
    account_type: AccountType,
) -> None:
    result, session, repository = await _select(account=_account(account_type=account_type))

    assert result == LiabilityBalanceEvidence(
        balance_id="balance-a",
        account_id="account-a",
        effective_at=NOW - timedelta(days=1),
        currency="CZK",
        outstanding_principal=Decimal("100"),
        accrued_interest=Decimal("2"),
        fees_outstanding=Decimal("3"),
        total_outstanding=Decimal("105"),
        source=LiabilityBalanceSource.statement,
    )
    assert repository.load_account_calls == ["account-a"]
    assert repository.load_balance_calls == [("account-a", NOW)]
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).total_outstanding = Decimal(0)
    cast(Any, session.begin).assert_not_called()
    cast(Any, session.begin_nested).assert_not_called()
    cast(Any, session.commit).assert_not_called()
    cast(Any, session.rollback).assert_not_called()
    cast(Any, session.flush).assert_not_called()


@pytest.mark.parametrize(
    ("principal", "interest", "fees", "total"),
    [
        (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
        (Decimal("100"), Decimal("0"), Decimal("0"), Decimal("100")),
        (Decimal("100"), Decimal("2"), Decimal("0"), Decimal("102")),
        (Decimal("100"), Decimal("0"), Decimal("3"), Decimal("103")),
        (Decimal("100"), Decimal("2"), Decimal("3"), Decimal("105")),
    ],
)
async def test_nonnegative_component_formula_is_exact(
    principal: Decimal,
    interest: Decimal,
    fees: Decimal,
    total: Decimal,
) -> None:
    result, _, _ = await _select(
        rows=(
            _balance(
                principal=principal,
                interest=interest,
                fees=fees,
                total=total,
            ),
        )
    )
    assert result.total_outstanding == total


async def test_latest_as_of_selection_is_deterministic_and_ignores_older_rows() -> None:
    older = _balance(
        balance_id="older",
        effective_at=NOW - timedelta(days=10),
        principal=Decimal("200"),
        interest=Decimal("0"),
        fees=Decimal("0"),
        total=Decimal("200"),
        external_id="older",
    )
    latest = _balance(balance_id="latest", external_id="latest")
    result, _, _ = await _select(rows=(latest, older))
    assert result.balance_id == "latest"


async def test_exact_snapshot_timestamp_is_eligible() -> None:
    result, _, _ = await _select(rows=(_balance(effective_at=NOW, created_at=NOW),))
    assert result.effective_at == NOW


@pytest.mark.parametrize(
    "account_type",
    [
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
    ],
)
async def test_non_liability_account_types_fail_before_balance_lookup(
    account_type: AccountType,
) -> None:
    repository = _Repository(_account(account_type=account_type), (_balance(),))
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await LiabilityBalanceEvidenceService(
            _session(),
            repository=repository,
        ).select(SelectLiabilityBalanceCommand("account-a", NOW))
    assert repository.load_balance_calls == []


@pytest.mark.parametrize(
    "account",
    [
        None,
        _account(archived=True),
        _account(account_id="other-account"),
        _account(currency="czk"),
    ],
)
async def test_missing_archived_or_corrupt_account_fails(
    account: AccountModel | None,
) -> None:
    repository = _Repository(account, (_balance(),))
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await LiabilityBalanceEvidenceService(
            _session(),
            repository=repository,
        ).select(SelectLiabilityBalanceCommand("account-a", NOW))


@pytest.mark.parametrize(
    "row",
    [
        _balance(currency="EUR"),
        _balance(account_id="other"),
        _balance(balance_id=" "),
        _balance(source="statement"),
        _balance(external_id=" "),
        _balance(effective_at=NOW + timedelta(milliseconds=1)),
        _balance(created_at=NOW.replace(microsecond=1)),
    ],
)
async def test_identity_currency_timestamp_and_source_corruption_fails(
    row: LiabilityBalanceModel,
) -> None:
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await _select(rows=(row,))


@pytest.mark.parametrize(
    "row",
    [
        _balance(principal=Decimal("-1"), total=Decimal("4")),
        _balance(interest=Decimal("-1"), total=Decimal("102")),
        _balance(fees=Decimal("-1"), total=Decimal("101")),
        _balance(total=Decimal("-105")),
        _balance(total=Decimal("104")),
        _balance(principal=Decimal("0.0000001"), total=Decimal("5.0000001")),
        _balance(principal=Decimal("1000000000000"), total=Decimal("1000000000005")),
        _balance(principal=1.0, total=Decimal("6")),
        _balance(principal=Decimal("NaN"), total=Decimal("NaN")),
        _balance(principal=Decimal("Infinity"), total=Decimal("Infinity")),
    ],
)
async def test_malformed_nonrepresentable_or_inexact_money_fails(
    row: LiabilityBalanceModel,
) -> None:
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await _select(rows=(row,))


async def test_two_sources_at_latest_timestamp_are_ambiguous() -> None:
    rows = (
        _balance(balance_id="statement", source=LiabilityBalanceSource.statement),
        _balance(
            balance_id="provider",
            source=LiabilityBalanceSource.provider,
            external_id="provider-a",
        ),
    )
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await _select(rows=rows)


async def test_duplicate_balance_identity_is_corruption_even_when_older() -> None:
    duplicate = _balance(balance_id="duplicate", effective_at=NOW - timedelta(days=2))
    rows = (
        _balance(balance_id="duplicate"),
        duplicate,
    )
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await _select(rows=rows)


async def test_malformed_latest_does_not_fall_back_to_valid_older_row() -> None:
    rows = (
        _balance(balance_id="latest", total=Decimal("104")),
        _balance(
            balance_id="older",
            effective_at=NOW - timedelta(days=10),
            external_id="older",
        ),
    )
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await _select(rows=rows)


async def test_no_eligible_balance_fails_without_zero_fallback() -> None:
    repository = _Repository(_account(), ())
    with pytest.raises(
        LiabilityBalanceEvidenceStateError,
        match=r"Liability balance evidence is unavailable\.",
    ):
        await LiabilityBalanceEvidenceService(
            _session(),
            repository=repository,
        ).select(SelectLiabilityBalanceCommand("account-a", NOW))


@pytest.mark.parametrize(
    "timestamp",
    [
        NOW.replace(microsecond=1),
        NOW.replace(tzinfo=UTC),
        "2026-07-28T10:20:00",
    ],
)
async def test_invalid_selection_timestamp_fails_before_repository(
    timestamp: object,
) -> None:
    repository = _Repository(_account(), (_balance(),))
    with pytest.raises(LiabilityBalanceEvidenceStateError):
        await LiabilityBalanceEvidenceService(
            _session(),
            repository=repository,
        ).select(
            SelectLiabilityBalanceCommand(
                "account-a",
                cast(Any, timestamp),
            )
        )
    assert repository.load_account_calls == []


async def test_selection_is_deterministic_and_does_not_mutate_rows() -> None:
    row = _balance()
    before = dict(row.__dict__)
    first, _, _ = await _select(rows=(row,))
    second, _, _ = await _select(rows=(row,))
    assert first == second
    assert row.__dict__ == before
