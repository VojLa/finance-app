"""Canonical ordering for replay roots."""

from __future__ import annotations

from datetime import datetime

from app.modules.portfolio_history_rebuild.models import (
    InvestmentEventRoot,
    LiabilityBalanceRoot,
    PortfolioHistoryReplayError,
    ReplayCursor,
    ReplayRoot,
    ReplayRootKind,
    TransactionRoot,
)

_KIND_PRIORITY = {
    ReplayRootKind.transaction: 0,
    ReplayRootKind.investment_event: 1,
    ReplayRootKind.liability_balance: 2,
}


def root_kind(root: ReplayRoot) -> ReplayRootKind:
    if isinstance(root, TransactionRoot):
        return ReplayRootKind.transaction
    if isinstance(root, InvestmentEventRoot):
        return ReplayRootKind.investment_event
    if isinstance(root, LiabilityBalanceRoot):
        return ReplayRootKind.liability_balance
    raise PortfolioHistoryReplayError("Unknown replay root type.")


def root_timestamp(root: ReplayRoot) -> datetime:
    if isinstance(root, TransactionRoot):
        return root.timestamp
    if isinstance(root, InvestmentEventRoot):
        return root.event_date
    if isinstance(root, LiabilityBalanceRoot):
        return root.effective_at
    raise PortfolioHistoryReplayError("Unknown replay root type.")


def root_entity_id(root: ReplayRoot) -> str:
    if isinstance(root, TransactionRoot):
        return root.transaction_id
    if isinstance(root, InvestmentEventRoot):
        return root.event_id
    if isinstance(root, LiabilityBalanceRoot):
        return root.balance_id
    raise PortfolioHistoryReplayError("Unknown replay root type.")


def root_order_key(root: ReplayRoot) -> tuple[datetime, int, str]:
    kind = root_kind(root)
    return root_timestamp(root), _KIND_PRIORITY[kind], root_entity_id(root)


def cursor_order_key(cursor: ReplayCursor) -> tuple[datetime, int, str]:
    return cursor.timestamp, _KIND_PRIORITY[cursor.kind], cursor.entity_id


def canonical_roots(roots: tuple[ReplayRoot, ...]) -> tuple[ReplayRoot, ...]:
    """Filter ineligible roots, reject duplicate identities, and sort canonically."""

    supported = (TransactionRoot, InvestmentEventRoot, LiabilityBalanceRoot)
    if not isinstance(roots, tuple) or any(not isinstance(root, supported) for root in roots):
        raise PortfolioHistoryReplayError("Replay roots must be a tuple of canonical root models.")
    if any(not isinstance(root.eligible, bool) for root in roots):
        raise PortfolioHistoryReplayError("Replay root eligibility must be a boolean.")
    eligible = tuple(root for root in roots if root.eligible)
    identities: set[tuple[ReplayRootKind, str]] = set()
    for root in eligible:
        identity = (root_kind(root), root_entity_id(root))
        if identity in identities:
            raise PortfolioHistoryReplayError("Duplicate replay root identity.")
        identities.add(identity)
    return tuple(sorted(eligible, key=root_order_key))
