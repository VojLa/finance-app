"""Stdin-only FastAPI/PostgreSQL bridge used by the R4 TypeScript acceptance test."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app


def _request() -> dict[str, Any]:
    if len(sys.argv) != 1:
        raise ValueError("Arguments are not accepted.")
    value = json.loads(sys.stdin.read())
    if not isinstance(value, dict):
        raise ValueError("The request must be an object.")
    return value


async def _seed(value: dict[str, Any]) -> dict[str, object]:
    database_url = value["database_url"]
    user_id = value["user_id"]
    foreign_user_id = value["foreign_user_id"]
    accounts = value["accounts"]
    if not isinstance(database_url, str) or not isinstance(accounts, list):
        raise ValueError("Invalid seed request.")
    engine = create_async_engine(normalize_database_url(database_url))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="R4 owner",
                    password_hash=None,
                    base_currency="EUR",
                    created_at=now,
                    updated_at=now,
                ),
                UserModel(
                    id=foreign_user_id,
                    email=f"{foreign_user_id}@example.test",
                    name="R4 foreign",
                    password_hash=None,
                    base_currency="EUR",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        for index, account in enumerate(accounts):
            account_id = account["id"]
            owner_id = foreign_user_id if account.get("foreign") else user_id
            account_type = AccountType(account["type"])
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=account_type,
                    currency=account["currency"],
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{account_id}-member",
                    account_id=account_id,
                    user_id=owner_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            if index % 2 == 0:
                await session.flush()
        for account in accounts:
            if account["type"] not in {"broker", "exchange"}:
                continue
            is_broker = account["type"] == "broker"
            symbol = "TSTETF" if is_broker else "BTC"
            asset_id = f"{account['id']}-asset"
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol=symbol,
                    isin="TEST00000001" if is_broker else None,
                    name=("Fictitious Test ETF" if is_broker else "Fictitious Test Bitcoin"),
                    asset_type=AssetType.etf if is_broker else AssetType.crypto,
                    currency="EUR" if is_broker else "BTC",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=f"{account['id']}-listing",
                    asset_id=asset_id,
                    symbol=symbol,
                    exchange="trading212" if is_broker else "anycoin",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker if is_broker else PriceSource.exchange,
                    provider_symbol=symbol,
                    is_primary=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()
    return {"ok": True}


async def _inspect(value: dict[str, Any]) -> dict[str, object]:
    database_url = value["database_url"]
    account_id = value["account_id"]
    engine = create_async_engine(normalize_database_url(database_url))
    async with AsyncSession(engine) as session:
        batch_ids = select(ImportBatchModel.id).where(ImportBatchModel.account_id == account_id)
        batches = await session.scalar(select(func.count()).select_from(batch_ids.subquery()))
        rows = await session.scalar(
            select(func.count())
            .select_from(ImportRowModel)
            .where(ImportRowModel.import_batch_id.in_(batch_ids))
        )
        transactions = await session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.account_id == account_id)
        )
        events = await session.scalar(
            select(func.count())
            .select_from(InvestmentEventModel)
            .where(InvestmentEventModel.account_id == account_id)
        )
    await engine.dispose()
    return {
        "ok": True,
        "batches": int(batches or 0),
        "rows": int(rows or 0),
        "transactions": int(transactions or 0),
        "events": int(events or 0),
    }


def _http(value: dict[str, Any]) -> dict[str, object]:
    database_url = value["database_url"]
    storage_root = value["storage_root"]
    secret = value["secret"]
    if not all(isinstance(item, str) for item in (database_url, storage_root, secret)):
        raise ValueError("Invalid HTTP bridge configuration.")
    os.environ["IMPORT_STORAGE_ROOT"] = storage_root
    settings = Settings(
        environment="test",
        database_url=database_url,
        log_level="ERROR",
        docs_enabled=False,
        internal_auth_secret=secret,
        internal_auth_issuer="finance-app-next",
        internal_auth_audience="finance-app-python",
        internal_auth_clock_skew_seconds=0,
    )
    body = base64.b64decode(value.get("body_base64", ""))
    headers = value.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError("Invalid request headers.")
    with TestClient(create_app(settings)) as client:
        response = client.request(
            method=value["method"],
            url=value["path"],
            headers={str(key): str(item) for key, item in headers.items()},
            content=body if body else None,
        )
    try:
        response_body: object = response.json()
    except ValueError:
        response_body = {"error": {"code": "non_json", "message": "Non-JSON response."}}
    return {
        "ok": True,
        "status": response.status_code,
        "content_type": response.headers.get("content-type", "application/json"),
        "body": response_body,
    }


def main() -> int:
    try:
        value = _request()
        action = value["action"]
        if action == "seed":
            result = asyncio.run(_seed(value))
        elif action == "inspect":
            result = asyncio.run(_inspect(value))
        elif action == "http":
            result = _http(value)
        else:
            raise ValueError("Unknown action.")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        result = {"ok": False, "error": type(error).__name__}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
