<!--
  GENERATED FILE — created by scripts/docs/generate_db_inventory.py.
  Do not edit manually; run the generator instead.
-->

# Database and Model Inventory

SQLAlchemy model classes are an inventory, not a schema specification. Alembic and the checked schema artifacts remain the executable schema authority.

## SQLAlchemy model files (19)

| Model file | Classes |
| --- | --- |
| `backend/python/app/db/models/accounts.py` | `AccountInviteModel`, `AccountMemberModel`, `AccountModel` |
| `backend/python/app/db/models/assets.py` | `AssetAliasModel`, `AssetListingModel`, `AssetModel` |
| `backend/python/app/db/models/background_jobs.py` | `BackgroundJobModel`, `ImportJobAffectedAccountModel`, `ImportJobBatchModel` |
| `backend/python/app/db/models/budgets.py` | `BudgetAccountModel`, `BudgetAlertModel`, `BudgetItemCategoryModel`, `BudgetItemModel`, `BudgetModel` |
| `backend/python/app/db/models/canonical_lineage.py` | `AccountCanonicalChangeModel`, `AccountCanonicalStateModel`, `AccountSnapshotCanonicalBoundaryModel`, `DailySnapshotBaselineAccountModel`, `DailySnapshotBaselineModel` |
| `backend/python/app/db/models/categories.py` | `CategoryModel`, `CategoryRuleModel` |
| `backend/python/app/db/models/common.py` | — |
| `backend/python/app/db/models/counterparties.py` | `CounterpartyAliasModel`, `CounterpartyModel` |
| `backend/python/app/db/models/enums.py` | `AccountInviteStatus`, `AccountMemberRole`, `AccountRelationType`, `AccountType`, `AliasMatchType`, `AssetAliasProvider`, `AssetType`, `BackgroundJobKind`, `BackgroundJobStatus`, `BudgetAlertType`, `BudgetPeriodType`, `CategoryType`, `CounterpartyType`, `ExchangeRateSource`, `HistoryGenerationBuildCause`, `HistoryGenerationState`, `ImportLogEvent`, `ImportLogLevel`, `ImportRowStatus`, `ImportSource`, `ImportStatus`, `InvestmentEventType`, `InvestmentMovementKind`, `LiabilityBalanceSource`, `MovementDirection`, `PortfolioHistoryCoverageStatus`, `PortfolioHistoryJobKind`, `PortfolioHistoryPointKind`, `PriceSource`, `RuleField`, `RuleOperator`, `SnapshotGranularity`, `SnapshotSource`, `TransactionClassification`, `TransactionType` |
| `backend/python/app/db/models/holdings.py` | `HoldingModel` |
| `backend/python/app/db/models/imports.py` | `ImportBatchModel`, `ImportLogModel`, `ImportRowModel`, `ImportSourceOccurrenceModel` |
| `backend/python/app/db/models/ledger.py` | `InvestmentEventModel`, `InvestmentMovementModel` |
| `backend/python/app/db/models/liabilities.py` | `LiabilityBalanceModel` |
| `backend/python/app/db/models/portfolio_history.py` | `PortfolioHistoryAccountPointModel`, `PortfolioHistoryCanonicalInvalidationModel`, `PortfolioHistoryCoverageSegmentModel`, `PortfolioHistoryDirtyStateModel`, `PortfolioHistoryGenerationAccountModel`, `PortfolioHistoryGenerationModel`, `PortfolioHistoryJobModel`, `PortfolioHistoryPointFxEvidenceModel`, `PortfolioHistoryPointModel`, `PortfolioHistoryPointPriceEvidenceModel`, `PortfolioHistoryPublicationModel`, `PortfolioHistoryReplayCheckpointModel`, `PortfolioHistoryScheduleStateModel` |
| `backend/python/app/db/models/prices.py` | `ExchangeRateModel`, `PriceSnapshotModel` |
| `backend/python/app/db/models/publication_targets.py` | `ImportJobPublicationTargetModel` |
| `backend/python/app/db/models/snapshots.py` | `AccountSnapshotItemModel`, `AccountSnapshotModel`, `NetWorthSnapshotModel` |
| `backend/python/app/db/models/transactions.py` | `TransactionModel`, `TransactionPairModel`, `TransactionReportingEvidenceModel`, `TransactionSplitModel` |
| `backend/python/app/db/models/users.py` | `UserModel` |

## Alembic revisions (14)

| Revision | Migration file |
| --- | --- |
| `3d0001base` | `backend/python/migrations/versions/3d0001base_prisma_schema_baseline.py` |
| `3e0001cutover` | `backend/python/migrations/versions/3e0001cutover_alembic_ownership.py` |
| `3f0001acctnote` | `backend/python/migrations/versions/3f0001acctnote_add_account_notes.py` |
| `3g0001liabbal` | `backend/python/migrations/versions/3g0001liabbal_add_liability_balances.py` |
| `3h0001twdata` | `backend/python/migrations/versions/3h0001twdata_add_twelve_data_provider_identity.py` |
| `3i0001d1base` | `backend/python/migrations/versions/3i0001d1base_add_daily_baseline_lineage.py` |
| `unknown` | `backend/python/migrations/versions/3j0001twfx_add_twelve_data_fx_source.py` |
| `3k0001mcost` | `backend/python/migrations/versions/3k0001mcost_add_multicurrency_holding_cost_basis.py` |
| `3l0001bgjob` | `backend/python/migrations/versions/3l0001bgjob_add_persisted_background_jobs.py` |
| `3m0001importanchor` | `backend/python/migrations/versions/3m0001importanchor_allow_minute_import_publication_anchor.py` |
| `3n0001emptyhold` | `backend/python/migrations/versions/3n0001emptyhold_initialize_empty_investment_holdings.py` |
| `3o0001unkbasis` | `backend/python/migrations/versions/3o0001unkbasis_allow_unknown_investment_cost_basis.py` |
| `3p0001rbfoundation` | `backend/python/migrations/versions/3p0001rbfoundation_add_reconciliation_schema_foundation.py` |
| `3q0001historygen` | `backend/python/migrations/versions/3q0001historygen_add_immutable_portfolio_history_generations.py` |

## Revision schema artifacts (12)

- `backend/python/database/revisions/3f0001acctnote/schema.sql`
- `backend/python/database/revisions/3g0001liabbal/schema.sql`
- `backend/python/database/revisions/3h0001twdata/schema.sql`
- `backend/python/database/revisions/3i0001d1base/schema.sql`
- `backend/python/database/revisions/3j0001twfx/schema.sql`
- `backend/python/database/revisions/3k0001mcost/schema.sql`
- `backend/python/database/revisions/3l0001bgjob/schema.sql`
- `backend/python/database/revisions/3m0001importanchor/schema.sql`
- `backend/python/database/revisions/3n0001emptyhold/schema.sql`
- `backend/python/database/revisions/3o0001unkbasis/schema.sql`
- `backend/python/database/revisions/3p0001rbfoundation/schema.sql`
- `backend/python/database/revisions/3q0001historygen/schema.sql`
