"""Server-operator CLI for explicit exact provider alias onboarding."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings  # noqa: E402
from app.db.connection import close_database, create_database  # noqa: E402
from app.db.models.enums import AssetAliasProvider, AssetType  # noqa: E402
from app.modules.asset_aliases import (  # noqa: E402
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasDecisionService,
    AssetAliasInvalidError,
    AssetAliasInventoryService,
    AssetAliasNotFoundError,
    AssetAliasOnboardingService,
    AssetAliasStateError,
    AssetListingCreationService,
    CreateAssetListingCommand,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
    RejectAssetAliasCommand,
    UnresolvedAssetAlias,
)

_ERROR_CODES: tuple[tuple[type[BaseException], str, int], ...] = (
    (AssetAliasInvalidError, "asset_alias_invalid", 2),
    (AssetAliasNotFoundError, "asset_alias_not_found", 3),
    (AssetAliasConflictError, "asset_alias_conflict", 4),
    (AssetAliasStateError, "asset_alias_state_error", 5),
    (AssetAliasDatabaseUnavailableError, "asset_alias_database_unavailable", 6),
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AssetAliasInvalidError() from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    unresolved = subparsers.add_parser("list-unresolved")
    unresolved.add_argument("--provider", required=True)

    health_summary = subparsers.add_parser("health-summary")
    health_summary.add_argument("--provider", required=True)

    onboard = subparsers.add_parser("onboard")
    onboard.add_argument("--actor", required=True)
    onboard.add_argument("--asset-id", required=True)
    onboard.add_argument("--listing-id")
    onboard.add_argument("--expected-symbol", required=True)
    onboard.add_argument("--expected-asset-type", required=True)
    onboard.add_argument("--expected-currency", required=True)
    onboard.add_argument("--expected-isin")
    onboard.add_argument("--provider", required=True)
    onboard.add_argument("--external-id", required=True)
    onboard.add_argument("--dry-run", action="store_true")
    reject = subparsers.add_parser("reject")
    reject.add_argument("--actor", required=True)
    reject.add_argument("--asset-id", required=True)
    reject.add_argument("--listing-id", required=True)
    reject.add_argument("--provider", required=True)
    reject.add_argument("--external-id", required=True)
    reject.add_argument("--reason", required=True)
    create_listing = subparsers.add_parser("create-listing")
    create_listing.add_argument("--actor", required=True)
    create_listing.add_argument("--asset-id", required=True)
    create_listing.add_argument("--expected-symbol", required=True)
    create_listing.add_argument("--expected-asset-type", required=True)
    create_listing.add_argument("--expected-currency", required=True)
    create_listing.add_argument("--expected-isin")
    create_listing.add_argument("--symbol", required=True)
    create_listing.add_argument("--exchange", required=True)
    create_listing.add_argument("--mic")
    create_listing.add_argument("--currency", required=True)
    create_listing.add_argument("--provider", required=True)
    create_listing.add_argument("--provider-symbol", required=True)
    create_listing.add_argument("--base-priority", type=int, default=0)
    return parser


def _provider(value: object) -> AssetAliasProvider:
    if not isinstance(value, str):
        raise AssetAliasInvalidError()
    try:
        provider = AssetAliasProvider(value)
    except ValueError as exc:
        raise AssetAliasInvalidError() from exc
    if provider not in {
        AssetAliasProvider.coingecko,
        AssetAliasProvider.twelve_data,
        AssetAliasProvider.yahoo_finance,
    }:
        raise AssetAliasInvalidError()
    return provider


def _asset_type(value: object) -> AssetType:
    if not isinstance(value, str):
        raise AssetAliasInvalidError()
    try:
        return AssetType(value)
    except ValueError as exc:
        raise AssetAliasInvalidError() from exc


def _created_at() -> datetime:
    current = datetime.now(UTC).replace(tzinfo=None)
    return current.replace(microsecond=(current.microsecond // 1_000) * 1_000)


def _result_document(result: OnboardAssetAliasResult) -> dict[str, object]:
    return {
        "aliasId": result.alias_id,
        "assetId": result.asset_id,
        "provider": result.provider.value,
        "externalId": result.external_id,
        "disposition": result.disposition.value,
    }


def _inventory_document(item: UnresolvedAssetAlias) -> dict[str, object]:
    return {
        "assetId": item.asset_id,
        "symbol": item.symbol,
        "assetType": item.asset_type.value,
        "currency": item.currency,
        "isin": item.isin,
        "listings": [
            {
                "listingId": listing.listing_id,
                "symbol": listing.symbol,
                "provider": (listing.provider.value if listing.provider is not None else None),
                "providerSymbol": listing.provider_symbol,
                "exchange": listing.exchange,
                "mic": listing.mic,
                "currency": listing.currency,
                "basePriority": listing.base_priority,
                "healthState": listing.health_state,
                "lastValidPriceAt": (
                    listing.last_valid_price_at.isoformat()
                    if listing.last_valid_price_at is not None
                    else None
                ),
            }
            for listing in item.listings
        ],
    }


async def _execute(args: argparse.Namespace) -> object:
    provider = _provider(args.provider)
    try:
        settings = Settings()
    except ValueError as exc:
        raise AssetAliasDatabaseUnavailableError() from exc
    database = create_database(settings)
    if database is None:
        raise AssetAliasDatabaseUnavailableError()
    try:
        async with database.session_factory() as session:
            if args.command == "list-unresolved":
                unresolved = await AssetAliasInventoryService(session).list_unresolved(provider)
                return [_inventory_document(item) for item in unresolved]
            if args.command == "health-summary":
                return await AssetAliasInventoryService(session).health_summary(provider)
            if args.command == "reject":
                rejected = await AssetAliasDecisionService(session).reject(
                    RejectAssetAliasCommand(
                        actor=args.actor,
                        asset_id=args.asset_id,
                        listing_id=args.listing_id,
                        provider=provider,
                        external_id=args.external_id,
                        reason=args.reason,
                    )
                )
                return {
                    "assetId": rejected.asset_id,
                    "listingId": rejected.listing_id,
                    "provider": rejected.provider.value,
                    "externalId": rejected.external_id,
                    "disposition": rejected.disposition,
                }
            if args.command == "create-listing":
                created = await AssetListingCreationService(session).create(
                    CreateAssetListingCommand(
                        actor=args.actor,
                        asset_id=args.asset_id,
                        expected_symbol=args.expected_symbol,
                        expected_asset_type=_asset_type(args.expected_asset_type),
                        expected_currency=args.expected_currency,
                        expected_isin=args.expected_isin,
                        symbol=args.symbol,
                        exchange=args.exchange,
                        mic=args.mic,
                        currency=args.currency,
                        provider=provider,
                        provider_symbol=args.provider_symbol,
                        base_priority=args.base_priority,
                        created_at=_created_at(),
                    )
                )
                return {
                    "listingId": created.listing_id,
                    "assetId": created.asset_id,
                    "provider": created.provider.value,
                    "providerSymbol": created.provider_symbol,
                    "disposition": created.disposition,
                }
            if args.command != "onboard":
                raise AssetAliasInvalidError()
            onboarded = await AssetAliasOnboardingService(session).onboard(
                OnboardAssetAliasCommand(
                    actor=args.actor,
                    asset_id=args.asset_id,
                    listing_id=args.listing_id,
                    provider=provider,
                    external_id=args.external_id,
                    expected_symbol=args.expected_symbol,
                    expected_asset_type=_asset_type(args.expected_asset_type),
                    expected_currency=args.expected_currency,
                    expected_isin=args.expected_isin,
                    created_at=_created_at(),
                ),
                dry_run=args.dry_run,
            )
            return _result_document(onboarded)
    finally:
        await close_database(database)


def _write_json(value: object, *, stream: TextIO) -> None:
    print(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        file=stream,
    )


def _error_result(error: BaseException) -> int:
    for error_type, code, exit_code in _ERROR_CODES:
        if isinstance(error, error_type):
            _write_json({"error": {"code": code}}, stream=sys.stderr)
            return exit_code
    _write_json({"error": {"code": "asset_alias_state_error"}}, stream=sys.stderr)
    return 5


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = asyncio.run(_execute(args))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        return _error_result(exc)
    _write_json(result, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
