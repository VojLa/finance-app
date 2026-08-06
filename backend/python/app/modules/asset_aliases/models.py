"""Immutable contracts for exact provider alias onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.db.models.enums import AssetAliasProvider, AssetType, PriceSource


class AssetAliasOnboardingError(Exception):
    """Base class for safe operator-facing onboarding failures."""


class AssetAliasInvalidError(AssetAliasOnboardingError):
    pass


class AssetAliasNotFoundError(AssetAliasOnboardingError):
    pass


class AssetAliasConflictError(AssetAliasOnboardingError):
    pass


class AssetAliasStateError(AssetAliasOnboardingError):
    pass


class AssetAliasDatabaseUnavailableError(AssetAliasOnboardingError):
    pass


class AssetAliasOnboardingDisposition(StrEnum):
    created = "created"
    replayed = "replayed"
    dry_run = "dry_run"


@dataclass(frozen=True, slots=True)
class OnboardAssetAliasCommand:
    asset_id: str
    provider: AssetAliasProvider
    external_id: str
    expected_symbol: str
    expected_asset_type: AssetType
    expected_currency: str
    expected_isin: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OnboardAssetAliasResult:
    alias_id: str | None
    asset_id: str
    provider: AssetAliasProvider
    external_id: str
    disposition: AssetAliasOnboardingDisposition


@dataclass(frozen=True, slots=True)
class UnresolvedAssetListing:
    listing_id: str
    provider: PriceSource | None
    provider_symbol: str | None
    exchange: str | None
    currency: str


@dataclass(frozen=True, slots=True)
class UnresolvedAssetAlias:
    asset_id: str
    symbol: str
    asset_type: AssetType
    currency: str
    isin: str | None
    listings: tuple[UnresolvedAssetListing, ...]


__all__ = [
    "AssetAliasConflictError",
    "AssetAliasDatabaseUnavailableError",
    "AssetAliasInvalidError",
    "AssetAliasNotFoundError",
    "AssetAliasOnboardingDisposition",
    "AssetAliasOnboardingError",
    "AssetAliasStateError",
    "OnboardAssetAliasCommand",
    "OnboardAssetAliasResult",
    "UnresolvedAssetAlias",
    "UnresolvedAssetListing",
]
