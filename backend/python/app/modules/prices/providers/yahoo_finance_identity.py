"""Exact persisted Yahoo Finance ticker identity for listed instruments."""

from __future__ import annotations

import re


class YahooFinanceAssetIdentityError(ValueError):
    """The value is not one exact canonical Yahoo Finance listed ticker."""


_TICKER = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}\Z")


def parse_yahoo_finance_asset_identity(value: object) -> str:
    if not isinstance(value, str) or not _TICKER.fullmatch(value):
        raise YahooFinanceAssetIdentityError()
    return value


__all__ = ["YahooFinanceAssetIdentityError", "parse_yahoo_finance_asset_identity"]
