from copy import deepcopy

from scripts.sqlalchemy_schema import compare_snapshots, local_snapshot, normalize_default


def test_local_snapshot_contains_complete_schema() -> None:
    snapshot = local_snapshot()

    assert len(snapshot["tables"]) == 63
    assert len(snapshot["enums"]) == 33
    generation = snapshot["tables"]["SnapshotGeneration"]
    assert [column["name"] for column in generation["columns"]] == [
        "id",
        "state",
        "createdAt",
        "publishedAt",
    ]
    target = snapshot["tables"]["SnapshotGenerationTarget"]
    assert [column["name"] for column in target["columns"]] == [
        "generationId",
        "userId",
        "createdAt",
        "stagedByJobId",
        "stagedLeaseVersion",
        "stagedLeaseOwner",
    ]
    schedule = snapshot["tables"]["SnapshotSeriesScheduleState"]
    assert [column["name"] for column in schedule["columns"]][-4:] == [
        "nextCaptureAt",
        "lastCapturedBucket",
        "lastDirtyEpoch",
        "updatedAt",
    ]
    investment = snapshot["tables"]["InvestmentAccountSnapshot"]
    assert [column["name"] for column in investment["columns"][:5]] == [
        "id",
        "accountSnapshotId",
        "accountId",
        "generationId",
        "timestamp",
    ]
    assert ["accountSnapshotId"] in investment["unique_constraints"]
    assert {
        "cashValueByCurrency",
        "investmentValueByCurrency",
        "investmentCostBasisByCurrency",
        "netDepositsByCurrency",
        "realizedPnlByCurrency",
        "unrealizedPnlByCurrency",
        "feesByCurrency",
        "taxesByCurrency",
        "priceEvidence",
        "exchangeRates",
    } <= {column["name"] for column in investment["columns"]}
    assert {
        "columns": ["accountSnapshotId", "generationId", "accountId"],
        "referred_schema": "public",
        "referred_table": "AccountSnapshot",
        "referred_columns": ["id", "generationId", "accountId"],
        "ondelete": "CASCADE",
    } in investment["foreign_keys"]
    portfolio = snapshot["tables"]["PortfolioSnapshot"]
    assert ["id", "generationId", "userId"] in portfolio["unique_constraints"]
    assert {
        "cashValueByCurrency",
        "investmentValueByCurrency",
        "investmentCostBasisByCurrency",
        "netDepositsByCurrency",
        "realizedPnlByCurrency",
        "unrealizedPnlByCurrency",
        "feesByCurrency",
        "taxesByCurrency",
        "priceEvidence",
        "exchangeRates",
    } <= {column["name"] for column in portfolio["columns"]}
    assert {
        "columns": ["generationId", "userId"],
        "referred_schema": "public",
        "referred_table": "SnapshotGenerationTarget",
        "referred_columns": ["generationId", "userId"],
        "ondelete": "RESTRICT",
    } in portfolio["foreign_keys"]
    input_link = snapshot["tables"]["PortfolioSnapshotInput"]
    assert {
        "columns": ["accountId", "userId"],
        "referred_schema": "public",
        "referred_table": "AccountMember",
        "referred_columns": ["accountId", "userId"],
        "ondelete": "RESTRICT",
    } not in input_link["foreign_keys"]
    account_breakdown = snapshot["tables"]["PortfolioSnapshotItemAccount"]
    assert {
        "columns": [
            "portfolioSnapshotItemId",
            "portfolioSnapshotId",
            "generationId",
            "userId",
            "listingId",
        ],
        "referred_schema": "public",
        "referred_table": "PortfolioSnapshotItem",
        "referred_columns": ["id", "portfolioSnapshotId", "generationId", "userId", "listingId"],
        "ondelete": "CASCADE",
    } in account_breakdown["foreign_keys"]
    valuation_evidence = snapshot["tables"]["InvestmentMovementValuationEvidence"]
    assert [column["name"] for column in valuation_evidence["columns"]] == [
        "id",
        "accountId",
        "movementId",
        "revision",
        "canonicalRevision",
        "effectiveAt",
        "calculationVersion",
        "selectionInterval",
        "inputFingerprint",
        "priceSnapshotId",
        "exchangeRateId",
        "priceAmount",
        "priceCurrency",
        "priceSource",
        "priceTimestamp",
        "fxRate",
        "fxFromCurrency",
        "fxToCurrency",
        "fxSource",
        "fxTimestamp",
        "pricePerUnit",
        "valueAmount",
        "valueCurrency",
        "createdAt",
    ]
    assert ["movementId", "revision"] in valuation_evidence["unique_constraints"]
    assert ["movementId", "inputFingerprint"] in valuation_evidence["unique_constraints"]
    assert {
        "columns": ["movementId"],
        "referred_schema": "public",
        "referred_table": "InvestmentMovement",
        "referred_columns": ["id"],
        "ondelete": "RESTRICT",
    } in valuation_evidence["foreign_keys"]


def test_schema_comparison_accepts_identical_snapshots(capsys) -> None:
    snapshot = local_snapshot()

    assert compare_snapshots(snapshot, snapshot) == 0
    assert "matches" in capsys.readouterr().out


def test_schema_comparison_reports_normalized_drift(capsys) -> None:
    expected = local_snapshot()
    actual = deepcopy(expected)
    actual["tables"]["Holding"]["columns"][4]["type"] = "numeric:28:8"

    assert compare_snapshots(expected, actual) == 1
    captured = capsys.readouterr()
    assert "SQLAlchemy metadata drift detected" in captured.err
    assert "numeric:28:10" in captured.err
    assert "numeric:28:8" in captured.err


def test_default_normalization_removes_schema_qualification() -> None:
    assert (
        normalize_default('\'viewer\'::"public"."AccountMemberRole"')
        == "'viewer'::accountmemberrole"
    )
