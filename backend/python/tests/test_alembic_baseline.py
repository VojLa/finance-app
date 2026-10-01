from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from scripts.alembic_baseline import (
    ASSET_ALIAS_AUDIT_REVISION,
    BACKGROUND_JOB_REVISION,
    BASELINE_REVISION,
    CUTOVER_REVISION,
    DAILY_BASELINE_REVISION,
    DIRECT_FX_REVISION,
    EMPTY_INVESTMENT_HOLDING_REVISION,
    HEAD_REVISION,
    HISTORY_GENERATION_REVISION,
    IMPORT_PUBLICATION_ANCHOR_REVISION,
    LISTING_MARKET_IDENTITY_REVISION,
    LISTING_PROVIDER_HEALTH_REVISION,
    MULTI_CURRENCY_COST_BASIS_REVISION,
    PREVIOUS_HEAD_REVISION,
    RB_SCHEMA_FOUNDATION_REVISION,
    UNKNOWN_INVESTMENT_COST_BASIS_REVISION,
    DatabaseState,
    verify_database_state,
    verify_manifest,
    verify_revision_graph,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = BACKEND_ROOT / "migrations" / "versions" / "3d0001base_prisma_schema_baseline.py"
CUTOVER_PATH = BACKEND_ROOT / "migrations" / "versions" / "3e0001cutover_alembic_ownership.py"
FIRST_HEAD_PATH = BACKEND_ROOT / "migrations" / "versions" / "3f0001acctnote_add_account_notes.py"
LIABILITY_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3g0001liabbal_add_liability_balances.py"
)
TWELVE_DATA_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3h0001twdata_add_twelve_data_provider_identity.py"
)
HEAD_PATH = BACKEND_ROOT / "migrations" / "versions" / "3i0001d1base_add_daily_baseline_lineage.py"
MULTI_CURRENCY_COST_BASIS_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3k0001mcost_add_multicurrency_holding_cost_basis.py"
)
BACKGROUND_JOB_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3l0001bgjob_add_persisted_background_jobs.py"
)
IMPORT_PUBLICATION_ANCHOR_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3m0001importanchor_allow_minute_import_publication_anchor.py"
)
EMPTY_INVESTMENT_HOLDING_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3n0001emptyhold_initialize_empty_investment_holdings.py"
)
UNKNOWN_INVESTMENT_COST_BASIS_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3o0001unkbasis_allow_unknown_investment_cost_basis.py"
)
RB_SCHEMA_FOUNDATION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3p0001rbfoundation_add_reconciliation_schema_foundation.py"
)
LISTING_PROVIDER_HEALTH_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "430001markethealth_add_listing_provider_health.py"
)
ASSET_ALIAS_AUDIT_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "440001assetaudit_add_operator_decision_audit.py"
)
OWNERSHIP_PATH = BACKEND_ROOT / "database" / "schema_ownership.toml"


def load_revision(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_upgrade_is_noop_and_downgrade_is_blocked() -> None:
    revision = load_revision(BASELINE_PATH, "prisma_schema_baseline")
    source = BASELINE_PATH.read_text(encoding="utf-8")

    assert revision.revision == BASELINE_REVISION
    assert revision.down_revision is None
    assert revision.upgrade() is None
    assert "op." not in source
    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_cutover_marker_is_noop_and_downgrade_is_blocked() -> None:
    revision = load_revision(CUTOVER_PATH, "alembic_ownership_cutover")
    source = CUTOVER_PATH.read_text(encoding="utf-8")

    assert revision.revision == CUTOVER_REVISION
    assert revision.down_revision == BASELINE_REVISION
    assert revision.ownership_cutover is True
    assert revision.prisma_schema_impact == "none"
    assert revision.upgrade() is None
    assert "op." not in source
    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_first_schema_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(FIRST_HEAD_PATH, "account_notes")
    source = FIRST_HEAD_PATH.read_text(encoding="utf-8")

    assert revision.revision == "3f0001acctnote"
    assert revision.down_revision == CUTOVER_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_nullable_column"
    assert revision.affected_tables == ("Account",)
    assert revision.affected_columns == ("Account.notes",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert "op.add_column" in source
    assert "op.drop_column" in source
    assert 'WHERE "notes" IS NOT NULL' in source


def test_liability_schema_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(LIABILITY_PATH, "liability_balances")
    source = LIABILITY_PATH.read_text(encoding="utf-8")

    assert revision.revision == "3g0001liabbal"
    assert revision.down_revision == "3f0001acctnote"
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_liability_balance_contract"
    assert revision.affected_tables == ("LiabilityBalance",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert "op.create_table" in source
    assert "op.drop_table" in source
    assert 'SELECT EXISTS (SELECT 1 FROM "public"."LiabilityBalance")' in source


def test_twelve_data_identity_revision_metadata_and_downgrade_policy() -> None:
    revision = load_revision(TWELVE_DATA_PATH, "twelve_data_provider_identity")
    source = TWELVE_DATA_PATH.read_text(encoding="utf-8")

    assert revision.revision == PREVIOUS_HEAD_REVISION
    assert revision.down_revision == "3g0001liabbal"
    assert revision.schema_change is True
    assert revision.schema_change_kind == "extend_market_provider_identity_enums"
    assert revision.affected_tables == ("AssetAlias", "AssetListing", "PriceSnapshot")
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert source.count("ADD VALUE IF NOT EXISTS 'twelve_data'") == 2
    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_listing_provider_health_revision_metadata_and_owned_types() -> None:
    revision = load_revision(LISTING_PROVIDER_HEALTH_PATH, "listing_provider_health")
    source = LISTING_PROVIDER_HEALTH_PATH.read_text(encoding="utf-8")

    assert revision.revision == LISTING_PROVIDER_HEALTH_REVISION
    assert revision.down_revision == LISTING_MARKET_IDENTITY_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_listing_provider_health"
    assert revision.affected_tables == ("MarketDataListingHealth",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert 'CREATE TYPE "public"."MarketDataHealthState" AS ENUM' in source
    assert 'CREATE TYPE "public"."MarketDataFailureReason" AS ENUM' in source
    assert '"MarketDataListingHealth"' in source


def test_asset_alias_audit_revision_metadata_and_append_only_guard() -> None:
    revision = load_revision(ASSET_ALIAS_AUDIT_PATH, "asset_alias_audit")
    source = ASSET_ALIAS_AUDIT_PATH.read_text(encoding="utf-8")

    assert revision.revision == ASSET_ALIAS_AUDIT_REVISION
    assert revision.down_revision == LISTING_PROVIDER_HEALTH_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_asset_alias_audit"
    assert revision.affected_tables == ("AssetAliasAudit",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert '"AssetAliasAudit"' in source
    assert "AssetAliasAudit_action_allowed" in source
    assert "prevent_asset_alias_audit_mutation" in source
    assert "AssetAliasAudit_append_only" in source


def test_daily_baseline_lineage_revision_metadata_and_backfill_contract() -> None:
    revision = load_revision(HEAD_PATH, "daily_baseline_lineage")
    source = HEAD_PATH.read_text(encoding="utf-8")

    assert revision.revision == DAILY_BASELINE_REVISION
    assert revision.down_revision == PREVIOUS_HEAD_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_daily_baseline_lineage"
    assert revision.data_migration is True
    assert set(revision.affected_tables) == {
        "AccountCanonicalState",
        "AccountCanonicalChange",
        "AccountSnapshotCanonicalBoundary",
        "DailySnapshotBaseline",
        "DailySnapshotBaselineAccount",
    }
    assert "row_number() OVER" in source
    assert '"holdingRevision"' in source
    assert 'DROP TABLE "public"."DailySnapshotBaseline"' not in source


def test_multicurrency_cost_basis_revision_metadata_and_data_loss_guards() -> None:
    revision = load_revision(MULTI_CURRENCY_COST_BASIS_PATH, "multicurrency_cost_basis")
    source = MULTI_CURRENCY_COST_BASIS_PATH.read_text(encoding="utf-8")

    assert revision.revision == MULTI_CURRENCY_COST_BASIS_REVISION
    assert revision.down_revision == DIRECT_FX_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_multicurrency_holding_cost_basis"
    assert revision.affected_tables == ("Holding", "AccountSnapshotItem")
    assert revision.data_migration is True
    assert "jsonb_typeof" in source
    assert "complete native cost pair" in source
    assert '"averageBuyPriceCurrency" <> "nativeCostCurrency"' in source
    assert "Cannot remove multi-currency or quote-average" in source


def test_background_job_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(BACKGROUND_JOB_PATH, "background_jobs")
    source = BACKGROUND_JOB_PATH.read_text(encoding="utf-8")

    assert revision.revision == BACKGROUND_JOB_REVISION
    assert revision.down_revision == MULTI_CURRENCY_COST_BASIS_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_persisted_background_job_lifecycle"
    assert revision.affected_tables == ("BackgroundJob",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert revision.STATUS_VALUES == ("queued", "running", "retry_wait", "completed", "failed")
    assert revision.KIND_VALUES == ("import_workflow",)
    for token in (
        '"maxAttempts" BETWEEN 1 AND 20',
        '"attemptCount" <= "maxAttempts"',
        "BackgroundJob_completed_has_result",
        "BackgroundJob_userId_accountId_kind_idempotencyKey_key",
        "BackgroundJob_claim_idx",
        "BackgroundJob_one_running_per_account_key",
        "Cannot remove BackgroundJob while durable job evidence exists.",
    ):
        assert token in source


def test_import_publication_anchor_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(IMPORT_PUBLICATION_ANCHOR_PATH, "import_publication_anchor")
    source = IMPORT_PUBLICATION_ANCHOR_PATH.read_text(encoding="utf-8")

    assert revision.revision == IMPORT_PUBLICATION_ANCHOR_REVISION
    assert revision.down_revision == BACKGROUND_JOB_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "allow_import_current_value_publication_anchor"
    assert revision.affected_tables == ("DailySnapshotBaseline", "ImportJobPublicationTarget")
    assert revision.affected_columns == (
        "DailySnapshotBaseline.granularity",
        "DailySnapshotBaseline.source",
        "DailySnapshotBaseline.backgroundJobId",
        "ImportJobPublicationTarget.jobId",
        "ImportJobPublicationTarget.userId",
        "ImportJobPublicationTarget.bucket",
        "ImportJobPublicationTarget.publishedAt",
    )
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    for token in (
        "DailySnapshotBaseline_day_only",
        "DailySnapshotBaseline_day_or_import_anchor",
        "\\'minute\\'::\"SnapshotGranularity\"",
        "\\'import_event\\'::\"SnapshotSource\"",
        '"backgroundJobId"',
        "ImportJobPublicationTarget",
        "DailySnapshotBaseline_backgroundJob_user_fkey",
        "Cannot remove minute import publication anchors while evidence exists.",
    ):
        assert token in source


def test_empty_investment_holding_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(EMPTY_INVESTMENT_HOLDING_PATH, "empty_investment_holding")
    source = EMPTY_INVESTMENT_HOLDING_PATH.read_text(encoding="utf-8")

    assert revision.revision == EMPTY_INVESTMENT_HOLDING_REVISION
    assert revision.down_revision == IMPORT_PUBLICATION_ANCHOR_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "initialize_empty_investment_holding_revision"
    assert revision.affected_tables == ("Account", "AccountCanonicalState", "Holding")
    assert revision.affected_columns == (
        "Account.type",
        "AccountCanonicalState.lastInvestmentRevision",
        "AccountCanonicalState.holdingRevision",
        "Holding.accountId",
    )
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is True
    for token in (
        'CREATE OR REPLACE FUNCTION "public"."initializeAccountCanonicalState"()',
        "'broker', 'exchange', 'crypto_wallet'",
        'state."lastInvestmentRevision" = 0',
        'state."holdingRevision" IS NULL',
        'FROM "public"."Holding" AS holding',
        'FROM "public"."AccountCanonicalChange" AS change',
        "Cannot remove initialized empty investment Holding revisions automatically.",
    ):
        assert token in source


def test_unknown_cost_basis_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(UNKNOWN_INVESTMENT_COST_BASIS_PATH, "unknown_cost_basis")
    source = UNKNOWN_INVESTMENT_COST_BASIS_PATH.read_text(encoding="utf-8")

    assert revision.revision == UNKNOWN_INVESTMENT_COST_BASIS_REVISION
    assert revision.down_revision == EMPTY_INVESTMENT_HOLDING_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "allow_unknown_investment_cost_basis"
    assert revision.affected_tables == ("Holding", "AccountSnapshot", "AccountSnapshotItem")
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    for token in (
        "Holding_cost_basis_completeness_pair",
        "AccountSnapshotItem_cost_basis_completeness",
        "Cannot remove unknown investment cost-basis support while incomplete evidence exists.",
    ):
        assert token in source


def test_reconciliation_foundation_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(RB_SCHEMA_FOUNDATION_PATH, "rb_schema_foundation")
    source = RB_SCHEMA_FOUNDATION_PATH.read_text(encoding="utf-8")

    assert revision.revision == RB_SCHEMA_FOUNDATION_REVISION
    assert revision.down_revision == UNKNOWN_INVESTMENT_COST_BASIS_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_import_reconciliation_evidence_foundation"
    assert revision.affected_tables == (
        "ImportBatch",
        "ImportRow",
        "Transaction",
        "ExchangeRate",
        "BackgroundJob",
        "ImportSourceOccurrence",
        "TransactionReportingEvidence",
        "ImportJobBatch",
        "ImportJobAffectedAccount",
        "TransactionPair",
    )
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is True
    for token in (
        "ImportSourceOccurrence_fp_identity_key",
        "ImportSourceOccurrence_ordinal_positive",
        '"ordinal" >= 1',
        "TransactionReportingEvidence_fx_direction_fkey",
        "ImportJobBatch_job_scope_fkey",
        "ImportJobAffectedAccount_member_fkey",
        "TransactionPair_reconciliation_evidence_complete_or_legacy",
        "Cannot remove import reconciliation evidence while durable evidence exists.",
    ):
        assert token in source


def test_manifest_records_first_alembic_schema_head() -> None:
    manifest = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    baseline = manifest["alembic_baseline"]
    alembic = manifest["alembic"]

    assert manifest["schema_version"] == 27
    assert manifest["current_migration_owner"] == "alembic"
    assert manifest["cutover_status"] == "completed"
    assert baseline["revision_count"] == 29
    assert baseline["head_revision"] == HEAD_REVISION
    assert alembic["head_revision"] == HEAD_REVISION
    assert alembic["revision_count"] == 29

    verify_manifest()
    verify_revision_graph()


def test_database_state_accepts_all_known_single_head_states() -> None:
    verify_database_state(DatabaseState(30, 27, ()))
    verify_database_state(DatabaseState(30, 27, (BASELINE_REVISION,)))
    verify_database_state(DatabaseState(30, 27, (CUTOVER_REVISION,)))
    verify_database_state(DatabaseState(30, 27, ("3f0001acctnote",)))
    verify_database_state(DatabaseState(31, 28, (PREVIOUS_HEAD_REVISION,)))
    verify_database_state(DatabaseState(36, 28, (MULTI_CURRENCY_COST_BASIS_REVISION,)))
    verify_database_state(DatabaseState(38, 30, (BACKGROUND_JOB_REVISION,)))
    verify_database_state(DatabaseState(38, 30, (IMPORT_PUBLICATION_ANCHOR_REVISION,)))
    verify_database_state(DatabaseState(38, 30, (UNKNOWN_INVESTMENT_COST_BASIS_REVISION,)))
    verify_database_state(DatabaseState(42, 30, (RB_SCHEMA_FOUNDATION_REVISION,)))
    verify_database_state(DatabaseState(54, 34, (HISTORY_GENERATION_REVISION,)))
    verify_database_state(DatabaseState(61, 31, (LISTING_MARKET_IDENTITY_REVISION,)))
    verify_database_state(DatabaseState(62, 33, (LISTING_PROVIDER_HEALTH_REVISION,)))
    verify_database_state(DatabaseState(63, 33, (ASSET_ALIAS_AUDIT_REVISION,)))


def test_database_state_rejects_schema_or_revision_drift() -> None:
    with pytest.raises(RuntimeError, match="Expected 63 application tables"):
        verify_database_state(DatabaseState(31, 30, (HEAD_REVISION,)))
    with pytest.raises(RuntimeError, match="Expected 33 enums"):
        verify_database_state(DatabaseState(63, 27, (HEAD_REVISION,)))
    with pytest.raises(RuntimeError, match="unknown Alembic revisions"):
        verify_database_state(DatabaseState(30, 27, ("unknown",)))
