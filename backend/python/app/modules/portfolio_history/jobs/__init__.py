"""Dedicated durable history-job lifecycle; intentionally separate from R12."""

from app.modules.portfolio_history.jobs.dispatch import PortfolioHistoryJobDispatchExecutor

__all__ = ["PortfolioHistoryJobDispatchExecutor"]
