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
    actor: str
    asset_id: str
    provider: AssetAliasProvider
    external_id: str
    expected_symbol: str
    expected_asset_type: AssetType
    expected_currency: str
    expected_isin: str | None
    created_at: datetime
    listing_id: str | None = None


@dataclass(frozen=True, slots=True)
class OnboardAssetAliasResult:
    alias_id: str | None
    asset_id: str
    provider: AssetAliasProvider
    external_id: str
    disposition: AssetAliasOnboardingDisposition


@dataclass(frozen=True, slots=True)
class RejectAssetAliasCommand:
    actor: str
    asset_id: str
    listing_id: str
    provider: AssetAliasProvider
    external_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RejectAssetAliasResult:
    asset_id: str
    listing_id: str
    provider: AssetAliasProvider
    external_id: str
    disposition: str = "rejected"


@dataclass(frozen=True, slots=True)
class CreateAssetListingCommand:
    actor: str
    asset_id: str
    expected_symbol: str
    expected_asset_type: AssetType
    expected_currency: str
    expected_isin: str | None
    symbol: str
    exchange: str
    mic: str | None
    currency: str
    provider: AssetAliasProvider
    provider_symbol: str
    base_priority: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CreateAssetListingResult:
    listing_id: str
    asset_id: str
    provider: AssetAliasProvider
    provider_symbol: str
    disposition: str


@dataclass(frozen=True, slots=True)
class UnresolvedAssetListing:
    listing_id: str
    symbol: str
    provider: PriceSource | None
    provider_symbol: str | None
    exchange: str | None
    mic: str | None
    currency: str
    base_priority: int
    health_state: str | None
    last_valid_price_at: datetime | None


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
    "CreateAssetListingCommand",
    "CreateAssetListingResult",
    "OnboardAssetAliasCommand",
    "OnboardAssetAliasResult",
    "RejectAssetAliasCommand",
    "RejectAssetAliasResult",
    "UnresolvedAssetAlias",
    "UnresolvedAssetListing",
]
