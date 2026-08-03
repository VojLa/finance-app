from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ImportSource,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r3-investment-fixture-secret-with-32-characters"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "imports"
MANIFEST_FIELDS = (
    "timestamp",
    "granularity",
    "currency",
    "calculationVersion",
    "accounts",
)


def engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


def settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        _env_file=None,
    )


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def token(user_id: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(
        SECRET.encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def headers(user_id: str, *, binary: bool = False) -> dict[str, str]:
    value = {"Authorization": f"Bearer {token(user_id)}"}
    if binary:
        value["Content-Type"] = "application/octet-stream"
    return value


async def cleanup(prefix: str) -> None:
    db = engine()
    async with AsyncSession(db) as session:
        account_ids = tuple(
            (
                await session.scalars(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            ).all()
        )
        user_ids = tuple(
            (
                await session.scalars(
                    select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-"))
                )
            ).all()
        )
        batch_ids = tuple(
            (
                await session.scalars(
                    select(ImportBatchModel.id).where(ImportBatchModel.account_id.in_(account_ids))
                )
            ).all()
        )
        event_ids = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.account_id.in_(account_ids)
                    )
                )
            ).all()
        )
        snapshot_ids = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel.id).where(
                        AccountSnapshotModel.account_id.in_(account_ids)
                    )
                )
            ).all()
        )
        listing_ids = tuple(
            value
            for value in (
                await session.scalars(
                    select(InvestmentMovementModel.listing_id).where(
                        InvestmentMovementModel.event_id.in_(event_ids)
                    )
                )
            ).all()
            if value
        )
        asset_ids = tuple(
            value
            for value in (
                await session.scalars(
                    select(InvestmentMovementModel.asset_id).where(
                        InvestmentMovementModel.event_id.in_(event_ids)
                    )
                )
            ).all()
            if value
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
        if account_ids:
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids))
            )
        if user_ids:
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
        if listing_ids:
            await session.execute(
                delete(PriceSnapshotModel).where(PriceSnapshotModel.listing_id.in_(listing_ids))
            )
        if event_ids:
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.event_id.in_(event_ids)
                )
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.id.in_(event_ids))
            )
        if batch_ids:
            await session.execute(
                delete(TransactionModel).where(TransactionModel.import_batch_id.in_(batch_ids))
            )
            await session.execute(
                delete(ImportLogModel).where(ImportLogModel.import_batch_id.in_(batch_ids))
            )
            await session.execute(
                delete(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
            )
            await session.execute(
                delete(ImportBatchModel).where(ImportBatchModel.id.in_(batch_ids))
            )
        if asset_ids:
            await session.execute(
                delete(AssetAliasModel).where(AssetAliasModel.asset_id.in_(asset_ids))
            )
        if listing_ids:
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id.in_(listing_ids))
            )
        if asset_ids:
            await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
        if account_ids:
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        if user_ids:
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await db.dispose()


async def seed_identity(
    prefix: str,
    *,
    source: ImportSource,
    second_account: bool = False,
) -> tuple[str, str]:
    await cleanup(prefix)
    db = engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    user_id = f"{prefix}-owner"
    account_id = f"{prefix}-account"
    account_type = AccountType.broker if source is ImportSource.trading212 else AccountType.exchange
    async with AsyncSession(db) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name="Synthetic fixture owner",
                password_hash=None,
                base_currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        accounts = [account_id]
        if second_account:
            accounts.append(f"{prefix}-account-two")
        for index, value in enumerate(accounts):
            session.add(
                AccountModel(
                    id=value,
                    name=f"Synthetic {source.value} account {index + 1}",
                    type=account_type,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for index, value in enumerate(accounts):
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member-{index}",
                    account_id=value,
                    user_id=user_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await db.dispose()
    return user_id, account_id


async def seed_asset_listing(prefix: str, *, source: ImportSource) -> tuple[str, str]:
    db = engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    if source is ImportSource.trading212:
        symbol = "TSTETF"
        isin = "TEST00000001"
        name = "Fictitious Test ETF"
        asset_type = AssetType.etf
        asset_currency = "EUR"
        provider = PriceSource.broker
    else:
        symbol = "BTC"
        isin = None
        name = "Fictitious Test Bitcoin"
        asset_type = AssetType.crypto
        asset_currency = "BTC"
        provider = PriceSource.exchange
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    async with AsyncSession(db) as session:
        session.add(
            AssetModel(
                id=asset_id,
                symbol=symbol,
                isin=isin,
                name=name,
                asset_type=asset_type,
                currency=asset_currency,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol=symbol,
                exchange=source.value,
                mic=None,
                currency="EUR",
                country=None,
                provider=provider,
                provider_symbol=symbol,
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await db.dispose()
    return asset_id, listing_id


async def seed_price(
    prefix: str,
    *,
    price: str,
    snapshot_timestamp: datetime,
) -> str:
    db = engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    price_id = f"{prefix}-price"
    async with AsyncSession(db) as session:
        session.add(
            PriceSnapshotModel(
                id=price_id,
                asset_id=f"{prefix}-asset",
                listing_id=f"{prefix}-listing",
                price=Decimal(price),
                currency="EUR",
                source=PriceSource.manual,
                timestamp=(snapshot_timestamp - timedelta(hours=1)).replace(tzinfo=None),
                created_at=now,
            )
        )
        await session.commit()
    await db.dispose()
    return price_id


def fixture(source: ImportSource, name: str) -> bytes:
    return (FIXTURES / source.value / name).read_bytes()


def variant(content: bytes, name: str) -> bytes:
    if name == "bom":
        return b"\xef\xbb\xbf" + content
    if name == "reordered":
        lines = content.decode("utf-8").splitlines()
        return ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode()
    return content


def run_stages(
    client: TestClient,
    *,
    source: ImportSource,
    user_id: str,
    account_id: str,
    content: bytes,
    filename: str,
    post: bool = True,
) -> dict[str, Any]:
    created = client.post(
        f"/api/v1/accounts/{account_id}/imports",
        headers=headers(user_id),
        json={
            "source": source.value,
            "filename": filename,
            "file_size": len(content),
            "file_encoding": None,
            "checksum": hashlib.sha256(content).hexdigest(),
        },
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]
    base = f"/api/v1/accounts/{account_id}/imports/{batch_id}"
    uploaded = client.put(
        f"{base}/file",
        headers=headers(user_id, binary=True),
        content=content,
    )
    assert uploaded.status_code == 200, uploaded.text
    result: dict[str, Any] = {"batch_id": batch_id, "created": created.json()}
    for stage in ("parse", "normalize", "deduplicate", "classify"):
        response = client.post(f"{base}/{stage}", headers=headers(user_id))
        assert response.status_code == 200, response.text
        result[stage] = response.json()
    if post:
        response = client.post(f"{base}/post", headers=headers(user_id))
        assert response.status_code == 200, response.text
        result["post"] = response.json()
    status = client.get(base, headers=headers(user_id))
    assert status.status_code == 200, status.text
    result["status"] = status.json()
    return result


def post_batch(
    client: TestClient,
    *,
    user_id: str,
    account_id: str,
    batch_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/accounts/{account_id}/imports/{batch_id}/post",
        headers=headers(user_id),
    )
    assert response.status_code == 200, response.text
    return response.json()
