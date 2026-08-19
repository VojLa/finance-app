"""Explicit, environment-gated market-evidence source selection.

The temporary ``local_free`` policy exists only to make local fixture work
possible while a licensed production feed is not configured.  It deliberately
does not provide a provider fallback: one asset type maps to one source and
every FX requirement maps to one direct-pair source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config.settings import Settings
from app.db.models.enums import AssetType, ExchangeRateSource, PriceSource

MarketEvidenceSourceMode = Literal["canonical", "local_free"]


class MarketEvidenceSourcePolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MarketEvidenceSourcePolicy:
    mode: MarketEvidenceSourceMode
    price_sources: frozenset[PriceSource]
    fx_source: ExchangeRateSource

    def price_source_for(self, asset_type: AssetType) -> PriceSource:
        if not isinstance(asset_type, AssetType):
            raise MarketEvidenceSourcePolicyError()
        if asset_type is AssetType.crypto:
            return PriceSource.coingecko
        if asset_type in {
            AssetType.stock,
            AssetType.etf,
            AssetType.bond,
            AssetType.commodity,
            AssetType.other,
        }:
            if self.mode == "canonical":
                return PriceSource.twelve_data
            return PriceSource.yahoo_finance
        raise MarketEvidenceSourcePolicyError()


CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY = MarketEvidenceSourcePolicy(
    mode="canonical",
    price_sources=frozenset({PriceSource.coingecko, PriceSource.twelve_data}),
    fx_source=ExchangeRateSource.twelve_data,
)

LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY = MarketEvidenceSourcePolicy(
    mode="local_free",
    price_sources=frozenset({PriceSource.coingecko, PriceSource.yahoo_finance}),
    fx_source=ExchangeRateSource.yahoo_finance,
)


def validate_market_evidence_source_policy(value: object) -> MarketEvidenceSourcePolicy:
    if value == CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY:
        return CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
    if value == LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY:
        return LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    raise MarketEvidenceSourcePolicyError()


def market_evidence_source_policy_from_settings(settings: Settings) -> MarketEvidenceSourcePolicy:
    if not isinstance(settings, Settings):
        raise MarketEvidenceSourcePolicyError()
    if settings.market_evidence_source_mode == "canonical":
        return CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
    if (
        settings.market_evidence_source_mode == "local_free"
        and settings.environment != "production"
    ):
        return LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    raise MarketEvidenceSourcePolicyError()


__all__ = [
    "CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY",
    "LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY",
    "MarketEvidenceSourceMode",
    "MarketEvidenceSourcePolicy",
    "MarketEvidenceSourcePolicyError",
    "market_evidence_source_policy_from_settings",
    "validate_market_evidence_source_policy",
]
