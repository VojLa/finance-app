"""One-pass chronological replay matrix and canonical generation checkpoints."""

from __future__ import annotations

from datetime import datetime

from app.modules.portfolio_history.builder.planning import HistoryGenerationBuildError
from app.modules.portfolio_history_rebuild.models import (
    AccountReplayState,
    empty_account_replay_state,
)
from app.modules.portfolio_history_rebuild.ordering import root_timestamp
from app.modules.portfolio_history_rebuild.replay import advance_account_replay
from app.modules.portfolio_history_rebuild.repository import FrozenPortfolioReplayInput


def replay_accounts_at(
    scope: FrozenPortfolioReplayInput,
    *,
    timestamps: tuple[datetime, ...],
) -> dict[datetime, dict[str, AccountReplayState]]:
    """Advance every account's canonical roots once across sorted timestamps."""

    if timestamps != tuple(sorted(set(timestamps))) or not timestamps:
        raise HistoryGenerationBuildError()
    matrix: dict[datetime, dict[str, AccountReplayState]] = {
        timestamp: {} for timestamp in timestamps
    }
    for account in scope.accounts:
        state = empty_account_replay_state(
            account_id=account.account_id,
            account_type=account.account_type,
            account_currency=account.account_currency,
        )
        cursor = 0
        for timestamp in timestamps:
            next_cursor = cursor
            while (
                next_cursor < len(account.roots)
                and root_timestamp(account.roots[next_cursor]) <= timestamp
            ):
                next_cursor += 1
            if next_cursor > cursor:
                state = advance_account_replay(state, account.roots[cursor:next_cursor])
                cursor = next_cursor
            matrix[timestamp][account.account_id] = state
    return matrix


__all__ = ["replay_accounts_at"]
