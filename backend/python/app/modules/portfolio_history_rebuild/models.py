"""Immutable inputs and replay state for chronological portfolio history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.db.models.enums import (
    AccountType,
    ImportSource,
    InvestmentEventType,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceMovement,
)


class PortfolioHistoryReplayError(ValueError):
    """The supplied canonical history cannot produce a deterministic state."""


class ReplayRootKind(StrEnum):
    transaction = "transaction"
    investment_event = "investment_event"
    liability_balance = "liability_balance"


@dataclass(frozen=True, slots=True)
class ReplayCursor:
    timestamp: datetime
    kind: ReplayRootKind
    entity_id: str


@dataclass(frozen=True, slots=True)
class TransactionRoot:
    transaction_id: str
    account_id: str
    timestamp: datetime
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    classification: TransactionClassification
    eligible: bool = True


@dataclass(frozen=True, slots=True)
class InvestmentEventRoot:
    event_id: str
    account_id: str
    event_type: InvestmentEventType
    event_date: datetime
    movements: tuple[HoldingPersistenceMovement, ...]
    source: ImportSource | None = None
    external_id: str | None = None
    realized_pnl: Decimal | None = None
    realized_pnl_currency: str | None = None
    eligible: bool = True


@dataclass(frozen=True, slots=True)
class LiabilityBalanceRoot:
    balance_id: str
    account_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal
    eligible: bool = True


ReplayRoot = TransactionRoot | InvestmentEventRoot | LiabilityBalanceRoot


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    net_deposits: tuple[CurrencyAmount, ...] = ()
    realized_pnl: tuple[CurrencyAmount, ...] = ()
    fees: tuple[CurrencyAmount, ...] = ()
    taxes: tuple[CurrencyAmount, ...] = ()
    has_asset_transfer: bool = False


@dataclass(frozen=True, slots=True)
class LiabilityReplayState:
    balance_id: str
    effective_at: datetime
    currency: str
    outstanding_principal: Decimal
    accrued_interest: Decimal
    fees_outstanding: Decimal
    total_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class AccountReplayState:
    account_id: str
    account_type: AccountType
    account_currency: str
    active: bool = False
    through: datetime | None = None
    cursor: ReplayCursor | None = None
    cash_by_currency: tuple[CurrencyAmount, ...] = ()
    holdings: tuple[ExpectedPersistedHoldingPlan, ...] = ()
    metrics: ReplayMetrics = ReplayMetrics()
    liability: LiabilityReplayState | None = None


def empty_account_replay_state(
    *, account_id: str, account_type: AccountType, account_currency: str
) -> AccountReplayState:
    """Create the structurally absent state before the first eligible root."""

    return AccountReplayState(
        account_id=account_id,
        account_type=account_type,
        account_currency=account_currency,
    )
