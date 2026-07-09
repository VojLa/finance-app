-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "AccountMemberRole" AS ENUM ('owner', 'admin', 'viewer', 'editor');

-- CreateEnum
CREATE TYPE "AccountRelationType" AS ENUM ('owner', 'joint_owner', 'manager', 'beneficiary', 'collaborator');

-- CreateEnum
CREATE TYPE "AccountInviteStatus" AS ENUM ('pending', 'accepted', 'revoked', 'expired');

-- CreateEnum
CREATE TYPE "AccountType" AS ENUM ('bank', 'cash', 'savings', 'broker', 'exchange', 'crypto_wallet', 'credit_card', 'loan', 'mortgage');

-- CreateEnum
CREATE TYPE "TransactionType" AS ENUM ('income', 'expense', 'transfer');

-- CreateEnum
CREATE TYPE "TransactionClassification" AS ENUM ('real_income', 'real_expense', 'internal_transfer', 'investment_transfer', 'loan_given', 'loan_received', 'loan_repayment', 'refund', 'cash_exchange', 'credit_card_payment', 'ignored', 'needs_review');

-- CreateEnum
CREATE TYPE "CounterpartyType" AS ENUM ('merchant', 'family', 'partner', 'friend', 'employer', 'broker', 'exchange', 'bank', 'service_provider', 'other');

-- CreateEnum
CREATE TYPE "AliasMatchType" AS ENUM ('exact', 'contains', 'starts_with', 'ends_with');

-- CreateEnum
CREATE TYPE "CategoryType" AS ENUM ('expense', 'income', 'both');

-- CreateEnum
CREATE TYPE "RuleField" AS ENUM ('description', 'counterparty');

-- CreateEnum
CREATE TYPE "RuleOperator" AS ENUM ('contains', 'equals', 'starts_with', 'ends_with', 'greater_than', 'less_than');

-- CreateEnum
CREATE TYPE "BudgetPeriodType" AS ENUM ('monthly', 'weekly', 'yearly', 'custom');

-- CreateEnum
CREATE TYPE "BudgetAlertType" AS ENUM ('approaching_limit', 'exceeded', 'reset');

-- CreateEnum
CREATE TYPE "AssetAliasProvider" AS ENUM ('coingecko', 'yahoo_finance', 'stooq', 'broker', 'exchange');

-- CreateEnum
CREATE TYPE "PriceSource" AS ENUM ('coingecko', 'yahoo_finance', 'stooq', 'manual', 'broker', 'exchange');

-- CreateEnum
CREATE TYPE "InvestmentEventType" AS ENUM ('trade', 'cash_deposit', 'cash_withdrawal', 'dividend', 'interest', 'currency_conversion', 'asset_transfer', 'fee', 'staking_reward', 'airdrop', 'adjustment');

-- CreateEnum
CREATE TYPE "InvestmentMovementKind" AS ENUM ('asset', 'cash', 'fee', 'tax');

-- CreateEnum
CREATE TYPE "MovementDirection" AS ENUM ('in', 'out');

-- CreateEnum
CREATE TYPE "AssetType" AS ENUM ('stock', 'etf', 'crypto', 'commodity', 'cash', 'bond', 'other');

-- CreateEnum
CREATE TYPE "ExchangeRateSource" AS ENUM ('cnb', 'ecb', 'manual', 'broker', 'exchange');

-- CreateEnum
CREATE TYPE "ImportSource" AS ENUM ('raiffeisenbank', 'trading212', 'anycoin', 'manual');

-- CreateEnum
CREATE TYPE "ImportStatus" AS ENUM ('pending', 'processing', 'completed', 'failed', 'partially_completed', 'cancelled');

-- CreateEnum
CREATE TYPE "ImportRowStatus" AS ENUM ('pending', 'imported', 'skipped', 'duplicate', 'failed', 'needs_review');

-- CreateEnum
CREATE TYPE "ImportLogLevel" AS ENUM ('info', 'warning', 'error');

-- CreateEnum
CREATE TYPE "ImportLogEvent" AS ENUM ('started', 'parse_error', 'validation_failed', 'dedup_skipped', 'holdings_recalculated', 'snapshots_recalculated', 'snapshot_validation_failed', 'completed', 'failed');

-- CreateEnum
CREATE TYPE "SnapshotGranularity" AS ENUM ('minute', 'hour', 'day', 'week', 'month');

-- CreateEnum
CREATE TYPE "SnapshotSource" AS ENUM ('import_event', 'price_refresh', 'holdings_recalculation', 'scheduled', 'manual_recalculation');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT,
    "passwordHash" TEXT,
    "baseCurrency" TEXT NOT NULL DEFAULT 'CZK',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" "AccountType" NOT NULL,
    "currency" TEXT NOT NULL,
    "color" TEXT,
    "isArchived" BOOLEAN NOT NULL DEFAULT false,
    "archivedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountMember" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "role" "AccountMemberRole" NOT NULL DEFAULT 'viewer',
    "relationType" "AccountRelationType" NOT NULL DEFAULT 'owner',
    "invitedById" TEXT,
    "acceptedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AccountMember_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountInvite" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "inviterId" TEXT NOT NULL,
    "acceptedById" TEXT,
    "email" TEXT NOT NULL,
    "role" "AccountMemberRole" NOT NULL DEFAULT 'viewer',
    "status" "AccountInviteStatus" NOT NULL DEFAULT 'pending',
    "tokenHash" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "acceptedAt" TIMESTAMP(3),
    "revokedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AccountInvite_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Transaction" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "bookingDate" TIMESTAMP(3),
    "amount" DECIMAL(18,6) NOT NULL,
    "currency" TEXT NOT NULL,
    "reportingAmount" DECIMAL(18,6),
    "reportingCurrency" TEXT,
    "type" "TransactionType" NOT NULL,
    "classification" "TransactionClassification",
    "description" TEXT,
    "note" TEXT,
    "counterparty" TEXT,
    "externalId" TEXT,
    "isReviewed" BOOLEAN NOT NULL DEFAULT false,
    "archivedAt" TIMESTAMP(3),
    "deletedAt" TIMESTAMP(3),
    "categoryId" TEXT,
    "accountId" TEXT NOT NULL,
    "importBatchId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Transaction_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TransactionPair" (
    "id" TEXT NOT NULL,
    "fromTransactionId" TEXT NOT NULL,
    "toTransactionId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TransactionPair_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TransactionSplit" (
    "id" TEXT NOT NULL,
    "transactionId" TEXT NOT NULL,
    "categoryId" TEXT,
    "amount" DECIMAL(18,6) NOT NULL,
    "currency" TEXT NOT NULL,
    "note" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TransactionSplit_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Counterparty" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" "CounterpartyType" NOT NULL DEFAULT 'other',
    "accountNumber" TEXT,
    "iban" TEXT,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Counterparty_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CounterpartyAlias" (
    "id" TEXT NOT NULL,
    "counterpartyId" TEXT NOT NULL,
    "alias" TEXT NOT NULL,
    "matchType" "AliasMatchType" NOT NULL DEFAULT 'contains',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CounterpartyAlias_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Category" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "icon" TEXT,
    "color" TEXT,
    "type" "CategoryType" NOT NULL,
    "parentId" TEXT,
    "isDefault" BOOLEAN NOT NULL DEFAULT false,
    "userId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Category_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CategoryRule" (
    "id" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "field" "RuleField" NOT NULL,
    "operator" "RuleOperator" NOT NULL DEFAULT 'contains',
    "classification" "TransactionClassification",
    "requiresReview" BOOLEAN NOT NULL DEFAULT false,
    "priority" INTEGER NOT NULL DEFAULT 0,
    "userId" TEXT,
    "categoryId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CategoryRule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Budget" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "periodStart" TIMESTAMP(3) NOT NULL,
    "periodEnd" TIMESTAMP(3) NOT NULL,
    "periodType" "BudgetPeriodType" NOT NULL DEFAULT 'monthly',
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "rolloverEnabled" BOOLEAN NOT NULL DEFAULT false,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Budget_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetItem" (
    "id" TEXT NOT NULL,
    "name" TEXT,
    "amount" DECIMAL(18,6) NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "rolloverAmount" DECIMAL(18,6),
    "budgetId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "BudgetItem_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetItemCategory" (
    "id" TEXT NOT NULL,
    "budgetItemId" TEXT NOT NULL,
    "categoryId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BudgetItemCategory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetAccount" (
    "id" TEXT NOT NULL,
    "budgetId" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BudgetAccount_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetAlert" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "budgetItemId" TEXT NOT NULL,
    "type" "BudgetAlertType" NOT NULL,
    "threshold" DECIMAL(5,4) NOT NULL,
    "triggeredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "acknowledgedAt" TIMESTAMP(3),

    CONSTRAINT "BudgetAlert_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Asset" (
    "id" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "isin" TEXT,
    "name" TEXT,
    "assetType" "AssetType" NOT NULL,
    "currency" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Asset_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssetListing" (
    "id" TEXT NOT NULL,
    "assetId" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "exchange" TEXT,
    "mic" TEXT,
    "currency" TEXT NOT NULL,
    "country" TEXT,
    "provider" "PriceSource",
    "providerSymbol" TEXT,
    "isPrimary" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AssetListing_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssetAlias" (
    "id" TEXT NOT NULL,
    "assetId" TEXT NOT NULL,
    "provider" "AssetAliasProvider" NOT NULL,
    "externalId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AssetAlias_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PriceSnapshot" (
    "id" TEXT NOT NULL,
    "assetId" TEXT NOT NULL,
    "listingId" TEXT,
    "price" DECIMAL(28,10) NOT NULL,
    "currency" TEXT NOT NULL,
    "source" "PriceSource" NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PriceSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "InvestmentEvent" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "type" "InvestmentEventType" NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "source" "ImportSource",
    "externalId" TEXT,
    "orderId" TEXT,
    "description" TEXT,
    "realizedPnl" DECIMAL(28,10),
    "realizedPnlCurrency" TEXT,
    "importBatchId" TEXT,
    "archivedAt" TIMESTAMP(3),
    "deletedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "InvestmentEvent_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "InvestmentMovement" (
    "id" TEXT NOT NULL,
    "eventId" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "assetId" TEXT,
    "kind" "InvestmentMovementKind" NOT NULL,
    "direction" "MovementDirection" NOT NULL,
    "quantity" DECIMAL(28,10) NOT NULL,
    "currency" TEXT NOT NULL,
    "pricePerUnit" DECIMAL(28,10),
    "valueAmount" DECIMAL(28,10),
    "valueCurrency" TEXT,
    "sourceSymbol" TEXT,
    "sourceAssetType" "AssetType",
    "note" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "InvestmentMovement_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Holding" (
    "id" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "name" TEXT,
    "assetType" "AssetType" NOT NULL,
    "quantity" DECIMAL(28,10) NOT NULL,
    "avgBuyPrice" DECIMAL(28,10) NOT NULL,
    "currency" TEXT NOT NULL,
    "currentPrice" DECIMAL(28,10),
    "currentValue" DECIMAL(28,10),
    "unrealizedPnl" DECIMAL(28,10),
    "realizedPnl" DECIMAL(28,10),
    "assetId" TEXT,
    "accountId" TEXT NOT NULL,
    "calculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Holding_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ExchangeRate" (
    "id" TEXT NOT NULL,
    "fromCurrency" TEXT NOT NULL,
    "toCurrency" TEXT NOT NULL,
    "rate" DECIMAL(18,8) NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "source" "ExchangeRateSource" NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ExchangeRate_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ImportBatch" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "source" "ImportSource" NOT NULL,
    "filename" TEXT NOT NULL,
    "fileSize" INTEGER,
    "fileEncoding" TEXT,
    "checksum" TEXT NOT NULL,
    "status" "ImportStatus" NOT NULL DEFAULT 'completed',
    "rowsTotal" INTEGER,
    "rowsImported" INTEGER,
    "rowsSkipped" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "retainUntil" TIMESTAMP(3),
    "rawDataPurgedAt" TIMESTAMP(3),

    CONSTRAINT "ImportBatch_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ImportRow" (
    "id" TEXT NOT NULL,
    "importBatchId" TEXT NOT NULL,
    "rowNumber" INTEGER NOT NULL,
    "rawData" JSONB NOT NULL,
    "normalizedData" JSONB,
    "validationErrors" JSONB,
    "deduplicationKey" TEXT,
    "status" "ImportRowStatus" NOT NULL DEFAULT 'pending',
    "errorMessage" TEXT,
    "createdTransactionId" TEXT,
    "createdInvestmentEventId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ImportRow_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ImportLog" (
    "id" TEXT NOT NULL,
    "importBatchId" TEXT NOT NULL,
    "level" "ImportLogLevel" NOT NULL,
    "event" "ImportLogEvent" NOT NULL,
    "message" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ImportLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "NetWorthSnapshot" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL,
    "granularity" "SnapshotGranularity" NOT NULL,
    "source" "SnapshotSource" NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "cashValue" DECIMAL(18,6) NOT NULL,
    "portfolioValue" DECIMAL(18,6) NOT NULL,
    "liabilitiesValue" DECIMAL(18,6) NOT NULL,
    "totalNetWorth" DECIMAL(18,6) NOT NULL,
    "isRecalculated" BOOLEAN NOT NULL DEFAULT false,
    "calculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "calculationVersion" INTEGER NOT NULL DEFAULT 1,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "NetWorthSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountSnapshot" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL,
    "granularity" "SnapshotGranularity" NOT NULL,
    "source" "SnapshotSource" NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "cashValue" DECIMAL(18,6) NOT NULL,
    "investmentValue" DECIMAL(18,6) NOT NULL,
    "investmentCostBasis" DECIMAL(18,6) NOT NULL DEFAULT 0,
    "liabilitiesValue" DECIMAL(18,6) NOT NULL,
    "totalValue" DECIMAL(18,6) NOT NULL,
    "isRecalculated" BOOLEAN NOT NULL DEFAULT false,
    "calculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "calculationVersion" INTEGER NOT NULL DEFAULT 1,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AccountSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountSnapshotItem" (
    "id" TEXT NOT NULL,
    "snapshotId" TEXT NOT NULL,
    "assetId" TEXT,
    "symbol" TEXT NOT NULL,
    "quantity" DECIMAL(28,10) NOT NULL,
    "pricePerUnit" DECIMAL(28,10) NOT NULL,
    "priceCurrency" TEXT,
    "priceSource" "PriceSource",
    "priceTimestamp" TIMESTAMP(3),
    "value" DECIMAL(18,6) NOT NULL,
    "costBasis" DECIMAL(28,10),
    "costCurrency" TEXT,
    "allocationPct" DECIMAL(8,4) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AccountSnapshotItem_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE INDEX "Account_type_idx" ON "Account"("type");

-- CreateIndex
CREATE INDEX "Account_isArchived_idx" ON "Account"("isArchived");

-- CreateIndex
CREATE INDEX "AccountMember_userId_idx" ON "AccountMember"("userId");

-- CreateIndex
CREATE INDEX "AccountMember_accountId_role_idx" ON "AccountMember"("accountId", "role");

-- CreateIndex
CREATE UNIQUE INDEX "AccountMember_accountId_userId_key" ON "AccountMember"("accountId", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "AccountInvite_tokenHash_key" ON "AccountInvite"("tokenHash");

-- CreateIndex
CREATE INDEX "AccountInvite_accountId_status_idx" ON "AccountInvite"("accountId", "status");

-- CreateIndex
CREATE INDEX "AccountInvite_email_status_idx" ON "AccountInvite"("email", "status");

-- CreateIndex
CREATE INDEX "AccountInvite_inviterId_createdAt_idx" ON "AccountInvite"("inviterId", "createdAt");

-- CreateIndex
CREATE INDEX "Transaction_accountId_date_idx" ON "Transaction"("accountId", "date");

-- CreateIndex
CREATE INDEX "Transaction_accountId_externalId_idx" ON "Transaction"("accountId", "externalId");

-- CreateIndex
CREATE INDEX "Transaction_categoryId_date_idx" ON "Transaction"("categoryId", "date");

-- CreateIndex
CREATE INDEX "Transaction_importBatchId_idx" ON "Transaction"("importBatchId");

-- CreateIndex
CREATE UNIQUE INDEX "TransactionPair_fromTransactionId_key" ON "TransactionPair"("fromTransactionId");

-- CreateIndex
CREATE UNIQUE INDEX "TransactionPair_toTransactionId_key" ON "TransactionPair"("toTransactionId");

-- CreateIndex
CREATE INDEX "TransactionSplit_transactionId_idx" ON "TransactionSplit"("transactionId");

-- CreateIndex
CREATE INDEX "TransactionSplit_categoryId_idx" ON "TransactionSplit"("categoryId");

-- CreateIndex
CREATE INDEX "Counterparty_userId_idx" ON "Counterparty"("userId");

-- CreateIndex
CREATE INDEX "Counterparty_userId_name_idx" ON "Counterparty"("userId", "name");

-- CreateIndex
CREATE INDEX "CounterpartyAlias_counterpartyId_idx" ON "CounterpartyAlias"("counterpartyId");

-- CreateIndex
CREATE INDEX "Category_userId_idx" ON "Category"("userId");

-- CreateIndex
CREATE INDEX "Category_parentId_idx" ON "Category"("parentId");

-- CreateIndex
CREATE INDEX "Category_userId_type_idx" ON "Category"("userId", "type");

-- CreateIndex
CREATE INDEX "CategoryRule_userId_idx" ON "CategoryRule"("userId");

-- CreateIndex
CREATE INDEX "CategoryRule_categoryId_idx" ON "CategoryRule"("categoryId");

-- CreateIndex
CREATE INDEX "CategoryRule_field_operator_idx" ON "CategoryRule"("field", "operator");

-- CreateIndex
CREATE INDEX "Budget_userId_periodStart_periodEnd_idx" ON "Budget"("userId", "periodStart", "periodEnd");

-- CreateIndex
CREATE UNIQUE INDEX "Budget_userId_periodStart_periodEnd_name_key" ON "Budget"("userId", "periodStart", "periodEnd", "name");

-- CreateIndex
CREATE INDEX "BudgetItem_budgetId_idx" ON "BudgetItem"("budgetId");

-- CreateIndex
CREATE INDEX "BudgetItemCategory_categoryId_idx" ON "BudgetItemCategory"("categoryId");

-- CreateIndex
CREATE UNIQUE INDEX "BudgetItemCategory_budgetItemId_categoryId_key" ON "BudgetItemCategory"("budgetItemId", "categoryId");

-- CreateIndex
CREATE INDEX "BudgetAccount_accountId_idx" ON "BudgetAccount"("accountId");

-- CreateIndex
CREATE UNIQUE INDEX "BudgetAccount_budgetId_accountId_key" ON "BudgetAccount"("budgetId", "accountId");

-- CreateIndex
CREATE INDEX "BudgetAlert_userId_triggeredAt_idx" ON "BudgetAlert"("userId", "triggeredAt");

-- CreateIndex
CREATE INDEX "BudgetAlert_budgetItemId_idx" ON "BudgetAlert"("budgetItemId");

-- CreateIndex
CREATE UNIQUE INDEX "Asset_symbol_key" ON "Asset"("symbol");

-- CreateIndex
CREATE INDEX "Asset_isin_idx" ON "Asset"("isin");

-- CreateIndex
CREATE INDEX "Asset_assetType_idx" ON "Asset"("assetType");

-- CreateIndex
CREATE INDEX "AssetListing_assetId_idx" ON "AssetListing"("assetId");

-- CreateIndex
CREATE INDEX "AssetListing_symbol_idx" ON "AssetListing"("symbol");

-- CreateIndex
CREATE INDEX "AssetListing_provider_providerSymbol_idx" ON "AssetListing"("provider", "providerSymbol");

-- CreateIndex
CREATE UNIQUE INDEX "AssetListing_assetId_symbol_exchange_currency_key" ON "AssetListing"("assetId", "symbol", "exchange", "currency");

-- CreateIndex
CREATE INDEX "AssetAlias_assetId_provider_idx" ON "AssetAlias"("assetId", "provider");

-- CreateIndex
CREATE UNIQUE INDEX "AssetAlias_provider_externalId_key" ON "AssetAlias"("provider", "externalId");

-- CreateIndex
CREATE INDEX "PriceSnapshot_assetId_timestamp_idx" ON "PriceSnapshot"("assetId", "timestamp");

-- CreateIndex
CREATE INDEX "PriceSnapshot_listingId_timestamp_idx" ON "PriceSnapshot"("listingId", "timestamp");

-- CreateIndex
CREATE INDEX "PriceSnapshot_source_timestamp_idx" ON "PriceSnapshot"("source", "timestamp");

-- CreateIndex
CREATE UNIQUE INDEX "PriceSnapshot_assetId_timestamp_source_key" ON "PriceSnapshot"("assetId", "timestamp", "source");

-- CreateIndex
CREATE INDEX "InvestmentEvent_accountId_date_idx" ON "InvestmentEvent"("accountId", "date");

-- CreateIndex
CREATE INDEX "InvestmentEvent_accountId_externalId_idx" ON "InvestmentEvent"("accountId", "externalId");

-- CreateIndex
CREATE INDEX "InvestmentEvent_orderId_idx" ON "InvestmentEvent"("orderId");

-- CreateIndex
CREATE INDEX "InvestmentEvent_importBatchId_idx" ON "InvestmentEvent"("importBatchId");

-- CreateIndex
CREATE INDEX "InvestmentMovement_eventId_idx" ON "InvestmentMovement"("eventId");

-- CreateIndex
CREATE INDEX "InvestmentMovement_accountId_createdAt_idx" ON "InvestmentMovement"("accountId", "createdAt");

-- CreateIndex
CREATE INDEX "InvestmentMovement_assetId_idx" ON "InvestmentMovement"("assetId");

-- CreateIndex
CREATE INDEX "InvestmentMovement_kind_idx" ON "InvestmentMovement"("kind");

-- CreateIndex
CREATE INDEX "Holding_accountId_idx" ON "Holding"("accountId");

-- CreateIndex
CREATE INDEX "Holding_assetId_idx" ON "Holding"("assetId");

-- CreateIndex
CREATE UNIQUE INDEX "Holding_symbol_accountId_key" ON "Holding"("symbol", "accountId");

-- CreateIndex
CREATE INDEX "ExchangeRate_fromCurrency_toCurrency_date_idx" ON "ExchangeRate"("fromCurrency", "toCurrency", "date");

-- CreateIndex
CREATE INDEX "ExchangeRate_source_date_idx" ON "ExchangeRate"("source", "date");

-- CreateIndex
CREATE UNIQUE INDEX "ExchangeRate_fromCurrency_toCurrency_date_source_key" ON "ExchangeRate"("fromCurrency", "toCurrency", "date", "source");

-- CreateIndex
CREATE INDEX "ImportBatch_userId_createdAt_idx" ON "ImportBatch"("userId", "createdAt");

-- CreateIndex
CREATE INDEX "ImportBatch_accountId_createdAt_idx" ON "ImportBatch"("accountId", "createdAt");

-- CreateIndex
CREATE INDEX "ImportBatch_source_status_idx" ON "ImportBatch"("source", "status");

-- CreateIndex
CREATE UNIQUE INDEX "ImportBatch_userId_accountId_checksum_key" ON "ImportBatch"("userId", "accountId", "checksum");

-- CreateIndex
CREATE INDEX "ImportRow_importBatchId_status_idx" ON "ImportRow"("importBatchId", "status");

-- CreateIndex
CREATE INDEX "ImportRow_deduplicationKey_idx" ON "ImportRow"("deduplicationKey");

-- CreateIndex
CREATE UNIQUE INDEX "ImportRow_importBatchId_rowNumber_key" ON "ImportRow"("importBatchId", "rowNumber");

-- CreateIndex
CREATE INDEX "ImportLog_importBatchId_createdAt_idx" ON "ImportLog"("importBatchId", "createdAt");

-- CreateIndex
CREATE INDEX "ImportLog_level_createdAt_idx" ON "ImportLog"("level", "createdAt");

-- CreateIndex
CREATE INDEX "NetWorthSnapshot_userId_granularity_timestamp_idx" ON "NetWorthSnapshot"("userId", "granularity", "timestamp");

-- CreateIndex
CREATE INDEX "NetWorthSnapshot_source_timestamp_idx" ON "NetWorthSnapshot"("source", "timestamp");

-- CreateIndex
CREATE UNIQUE INDEX "NetWorthSnapshot_userId_timestamp_currency_granularity_key" ON "NetWorthSnapshot"("userId", "timestamp", "currency", "granularity");

-- CreateIndex
CREATE INDEX "AccountSnapshot_accountId_granularity_timestamp_idx" ON "AccountSnapshot"("accountId", "granularity", "timestamp");

-- CreateIndex
CREATE INDEX "AccountSnapshot_source_timestamp_idx" ON "AccountSnapshot"("source", "timestamp");

-- CreateIndex
CREATE UNIQUE INDEX "AccountSnapshot_accountId_timestamp_currency_granularity_key" ON "AccountSnapshot"("accountId", "timestamp", "currency", "granularity");

-- CreateIndex
CREATE INDEX "AccountSnapshotItem_assetId_idx" ON "AccountSnapshotItem"("assetId");

-- CreateIndex
CREATE UNIQUE INDEX "AccountSnapshotItem_snapshotId_symbol_key" ON "AccountSnapshotItem"("snapshotId", "symbol");

-- AddForeignKey
ALTER TABLE "AccountMember" ADD CONSTRAINT "AccountMember_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountMember" ADD CONSTRAINT "AccountMember_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountInvite" ADD CONSTRAINT "AccountInvite_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountInvite" ADD CONSTRAINT "AccountInvite_inviterId_fkey" FOREIGN KEY ("inviterId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountInvite" ADD CONSTRAINT "AccountInvite_acceptedById_fkey" FOREIGN KEY ("acceptedById") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "Category"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "ImportBatch"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransactionPair" ADD CONSTRAINT "TransactionPair_fromTransactionId_fkey" FOREIGN KEY ("fromTransactionId") REFERENCES "Transaction"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransactionPair" ADD CONSTRAINT "TransactionPair_toTransactionId_fkey" FOREIGN KEY ("toTransactionId") REFERENCES "Transaction"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransactionSplit" ADD CONSTRAINT "TransactionSplit_transactionId_fkey" FOREIGN KEY ("transactionId") REFERENCES "Transaction"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransactionSplit" ADD CONSTRAINT "TransactionSplit_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "Category"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Counterparty" ADD CONSTRAINT "Counterparty_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CounterpartyAlias" ADD CONSTRAINT "CounterpartyAlias_counterpartyId_fkey" FOREIGN KEY ("counterpartyId") REFERENCES "Counterparty"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Category" ADD CONSTRAINT "Category_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES "Category"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CategoryRule" ADD CONSTRAINT "CategoryRule_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "Category"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Budget" ADD CONSTRAINT "Budget_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetItem" ADD CONSTRAINT "BudgetItem_budgetId_fkey" FOREIGN KEY ("budgetId") REFERENCES "Budget"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetItemCategory" ADD CONSTRAINT "BudgetItemCategory_budgetItemId_fkey" FOREIGN KEY ("budgetItemId") REFERENCES "BudgetItem"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetItemCategory" ADD CONSTRAINT "BudgetItemCategory_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "Category"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAccount" ADD CONSTRAINT "BudgetAccount_budgetId_fkey" FOREIGN KEY ("budgetId") REFERENCES "Budget"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAccount" ADD CONSTRAINT "BudgetAccount_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAlert" ADD CONSTRAINT "BudgetAlert_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAlert" ADD CONSTRAINT "BudgetAlert_budgetItemId_fkey" FOREIGN KEY ("budgetItemId") REFERENCES "BudgetItem"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssetListing" ADD CONSTRAINT "AssetListing_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssetAlias" ADD CONSTRAINT "AssetAlias_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PriceSnapshot" ADD CONSTRAINT "PriceSnapshot_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PriceSnapshot" ADD CONSTRAINT "PriceSnapshot_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "AssetListing"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentEvent" ADD CONSTRAINT "InvestmentEvent_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentEvent" ADD CONSTRAINT "InvestmentEvent_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "ImportBatch"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentMovement" ADD CONSTRAINT "InvestmentMovement_eventId_fkey" FOREIGN KEY ("eventId") REFERENCES "InvestmentEvent"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentMovement" ADD CONSTRAINT "InvestmentMovement_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentMovement" ADD CONSTRAINT "InvestmentMovement_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Holding" ADD CONSTRAINT "Holding_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Holding" ADD CONSTRAINT "Holding_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ImportBatch" ADD CONSTRAINT "ImportBatch_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ImportBatch" ADD CONSTRAINT "ImportBatch_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ImportRow" ADD CONSTRAINT "ImportRow_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "ImportBatch"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ImportLog" ADD CONSTRAINT "ImportLog_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "ImportBatch"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "NetWorthSnapshot" ADD CONSTRAINT "NetWorthSnapshot_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountSnapshot" ADD CONSTRAINT "AccountSnapshot_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountSnapshotItem" ADD CONSTRAINT "AccountSnapshotItem_snapshotId_fkey" FOREIGN KEY ("snapshotId") REFERENCES "AccountSnapshot"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountSnapshotItem" ADD CONSTRAINT "AccountSnapshotItem_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE SET NULL ON UPDATE CASCADE;

