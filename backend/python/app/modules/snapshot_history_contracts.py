"""Neutral public state and range contracts for snapshot-backed history."""

from enum import StrEnum

from app.shared.errors import ApplicationError


class PortfolioHistoryReadState(StrEnum):
    ready = "ready"
    rebuilding = "rebuilding"
    failed = "failed"
    empty = "empty"


class HistoryPublicRange(StrEnum):
    one_day = "1D"
    one_week = "1W"
    one_month = "1M"
    three_months = "3M"
    six_months = "6M"
    one_year = "1Y"
    five_years = "5Y"
    ten_years = "10Y"
    all = "ALL"


class PortfolioSnapshotHistoryUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="portfolio_history_unavailable",
            message="Portfolio history is unavailable.",
            status_code=409,
        )


__all__ = [
    "HistoryPublicRange",
    "PortfolioHistoryReadState",
    "PortfolioSnapshotHistoryUnavailableError",
]
