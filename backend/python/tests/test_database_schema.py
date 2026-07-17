from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

from scripts.database_schema import normalize_database_url, normalize_schema_dump

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
OWNERSHIP_PATH = BACKEND_ROOT / "database" / "schema_ownership.toml"
BASELINE_PATH = BACKEND_ROOT / "database" / "baseline" / "schema.sql"
CHECKSUM_PATH = BACKEND_ROOT / "database" / "baseline" / "schema.sha256"
PRISMA_SCHEMA_PATH = REPOSITORY_ROOT / "prisma" / "schema.prisma"

PRISMA_OBJECT_PATTERN = re.compile(r"^\s*(model|enum)\s+(\w+)\s+\{", re.MULTILINE)
BASELINE_TABLE_PATTERN = re.compile(r'CREATE TABLE "public"\."([^"]+)"')
BASELINE_ENUM_PATTERN = re.compile(r'CREATE TYPE "public"\."([^"]+)" AS ENUM')


def load_manifest() -> dict[str, Any]:
    with OWNERSHIP_PATH.open("rb") as manifest_file:
        return tomllib.load(manifest_file)


def flatten_domains(domains: dict[str, list[str]]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for domain, names in domains.items():
        for name in names:
            assert name not in flattened, f"Duplicate database object in manifest: {name}"
            flattened[name] = domain
    return flattened


def prisma_objects() -> tuple[set[str], set[str]]:
    schema = PRISMA_SCHEMA_PATH.read_text(encoding="utf-8")
    models: set[str] = set()
    enums: set[str] = set()
    for object_kind, name in PRISMA_OBJECT_PATTERN.findall(schema):
        target = models if object_kind == "model" else enums
        target.add(name)
    return models, enums


def manifest_objects() -> tuple[dict[str, str], dict[str, str]]:
    manifest = load_manifest()
    objects = manifest["objects"]
    return flatten_domains(objects["tables"]), flatten_domains(objects["enums"])


def baseline_objects() -> tuple[set[str], set[str]]:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    tables = set(BASELINE_TABLE_PATTERN.findall(baseline))
    enums = set(BASELINE_ENUM_PATTERN.findall(baseline))
    return tables, enums


def test_ownership_manifest_matches_prisma_models_and_enums() -> None:
    prisma_models, prisma_enums = prisma_objects()
    manifest_tables, manifest_enums = manifest_objects()

    assert set(manifest_tables) == prisma_models
    assert set(manifest_enums) == prisma_enums


def test_baseline_matches_ownership_manifest() -> None:
    manifest_tables, manifest_enums = manifest_objects()
    baseline_tables, baseline_enums = baseline_objects()

    assert baseline_tables == set(manifest_tables)
    assert baseline_enums == set(manifest_enums)
    assert "_prisma_migrations" not in baseline_tables


def test_all_objects_remain_prisma_owned_before_cutover() -> None:
    manifest = load_manifest()

    assert manifest["current_migration_owner"] == "prisma"
    assert manifest["target_migration_owner"] == "alembic"
    assert manifest["cutover_status"] == "not_started"
    assert manifest["defaults"] == {
        "current_owner": "prisma",
        "target_owner": "alembic",
        "cutover_status": "prisma_owned",
    }


def test_python_persistence_slice_is_explicit() -> None:
    usage = load_manifest()["python_usage"]

    assert set(usage["read_tables"]) == {
        "Account",
        "AccountMember",
        "ExchangeRate",
        "Holding",
    }
    assert usage["read_enums"] == []
    assert set(usage["transitive_read_tables"]) == {
        "Asset",
        "AssetListing",
        "User",
    }
    assert set(usage["transitive_read_enums"]) == {
        "AccountMemberRole",
        "AccountRelationType",
        "AccountType",
        "AssetType",
        "ExchangeRateSource",
        "PriceSource",
    }


def test_baseline_checksum_is_valid() -> None:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    expected_digest = CHECKSUM_PATH.read_text(encoding="utf-8").split()[0]

    assert hashlib.sha256(baseline.encode("utf-8")).hexdigest() == expected_digest


def test_normalize_database_url_removes_prisma_schema_parameter() -> None:
    database_url = "postgresql://user:password@localhost/app?schema=public&sslmode=require"

    assert normalize_database_url(database_url) == (
        "postgresql://user:password@localhost/app?sslmode=require"
    )


def test_normalize_schema_dump_removes_version_noise() -> None:
    raw_dump = (
        "-- Dumped from database version 16.4\r\n"
        "-- Dumped by pg_dump version 16.4\r\n"
        "\\restrict random-token\r\n"
        "SET transaction_timeout = 0;\r\n"
        "\r\n"
        "CREATE TABLE test ();\r\n"
        "\\unrestrict random-token\r\n"
    )

    assert normalize_schema_dump(raw_dump) == "CREATE TABLE test ();\n"
