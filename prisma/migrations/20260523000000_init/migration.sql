-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "ShareRole" AS ENUM ('viewer', 'editor');

-- CreateEnum
CREATE TYPE "AccountType" AS ENUM ('bank', 'cash', 'savings', 'broker', 'exchange', 'crypto_wallet', 'credit_card', 'loan', 'mortgage');

-- CreateEnum
CREATE TYPE "AccountOwnershipType" AS ENUM ('single_owner', 'joint_owner', 'child_managed');

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
CREATE TYPE "InvestmentType" AS ENUM ('buy', 'sell', 'deposit', 'withdrawal', 'dividend', 'interest', 'currency_conversion', 'staking_reward', 'airdrop', 'fee', 'transfer');

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
CREATE TYPE "ImportLogEvent" AS ENUM ('started', 'parse_error', 'validation_failed', 'dedup_skipped', 'holdings_recalculated', 'completed', 'failed');

-- CreateEnum
CREATE TYPE "SnapshotGranularity" AS ENUM ('minute', 'hour', 'day', 'week', 'month');

-- CreateEnum
CREATE TYPE "PortfolioSnapshotSource" AS ENUM ('import_event', 'price_refresh', 'holdings_recalculation', 'scheduled', 'manual_recalculation');

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
    "ownershipType" "AccountOwnershipType" NOT NULL DEFAULT 'single_owner',
    "isArchived" BOOLEAN NOT NULL DEFAULT false,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountShare" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "sharedWithId" TEXT NOT NULL,
    "role" "ShareRole" NOT NULL DEFAULT 'viewer',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AccountShare_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Transaction" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "bookingDate" TIMESTAMP(3),
    "amount" DECIMAL(18,6) NOT NULL,
    "currency" TEXT NOT NULL,
    "amountCzk" DECIMAL(18,6),
    "type" "TransactionType" NOT NULL,
    "classification" "TransactionClassification",
    "description" TEXT,
    "note" TEXT,
    "counterparty" TEXT,
    "externalId" TEXT,
    "isReviewed" BOOLEAN NOT NULL DEFAULT false,
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
    "month" INTEGER NOT NULL,
    "year" INTEGER NOT NULL,
    "periodType" "BudgetPeriodType" NOT NULL DEFAULT 'monthly',
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "rollover" BOOLEAN NOT NULL DEFAULT false,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Budget_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetItem" (
    "id" TEXT NOT NULL,
    "amount" DECIMAL(18,6) NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "rolloverAmount" DECIMAL(18,6),
    "budgetId" TEXT NOT NULL,
    "categoryId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "BudgetItem_pkey" PRIMARY KEY ("id")
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
    "price" DECIMAL(28,10) NOT NULL,
    "currency" TEXT NOT NULL,
    "source" "PriceSource" NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PriceSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "InvestmentTransaction" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "type" "InvestmentType" NOT NULL,
    "assetId" TEXT,
    "symbol" TEXT,
    "isin" TEXT,
    "name" TEXT,
    "assetType" "AssetType",
    "quantity" DECIMAL(28,10),
    "pricePerUnit" DECIMAL(28,10),
    "priceCurrency" TEXT,
    "totalAmount" DECIMAL(28,10),
    "totalCurrency" TEXT,
    "fee" DECIMAL(18,6),
    "feeCurrency" TEXT,
    "exchangeRate" DECIMAL(18,8),
    "orderId" TEXT,
    "externalId" TEXT,
    "realizedPnl" DECIMAL(28,10),
    "realizedPnlCurrency" TEXT,
    "accountId" TEXT NOT NULL,
    "importBatchId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "InvestmentTransaction_pkey" PRIMARY KEY ("id")
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
    "createdInvestmentTransactionId" TEXT,
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
    "date" TIMESTAMP(3) NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "cashValue" DECIMAL(18,6) NOT NULL,
    "portfolioValue" DECIMAL(18,6) NOT NULL,
    "liabilitiesValue" DECIMAL(18,6) NOT NULL,
    "totalNetWorth" DECIMAL(18,6) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "NetWorthSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PortfolioSnapshot" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL,
    "granularity" "SnapshotGranularity" NOT NULL,
    "source" "PortfolioSnapshotSource" NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'CZK',
    "totalValue" DECIMAL(18,6) NOT NULL,
    "isRecalculated" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PortfolioSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PortfolioSnapshotItem" (
    "id" TEXT NOT NULL,
    "snapshotId" TEXT NOT NULL,
    "assetId" TEXT,
    "symbol" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "quantity" DECIMAL(28,10) NOT NULL,
    "pricePerUnit" DECIMAL(28,10) NOT NULL,
    "value" DECIMAL(18,6) NOT NULL,
    "allocationPct" DECIMAL(8,4) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PortfolioSnapshotItem_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "AccountShare_accountId_sharedWithId_key" ON "AccountShare"("accountId", "sharedWithId");

-- CreateIndex
CREATE UNIQUE INDEX "TransactionPair_fromTransactionId_key" ON "TransactionPair"("fromTransactionId");

-- CreateIndex
CREATE UNIQUE INDEX "TransactionPair_toTransactionId_key" ON "TransactionPair"("toTransactionId");

-- CreateIndex
CREATE UNIQUE INDEX "Budget_month_year_userId_key" ON "Budget"("month", "year", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "BudgetItem_budgetId_categoryId_key" ON "BudgetItem"("budgetId", "categoryId");

-- CreateIndex
CREATE UNIQUE INDEX "Asset_symbol_key" ON "Asset"("symbol");

-- CreateIndex
CREATE UNIQUE INDEX "AssetAlias_assetId_provider_key" ON "AssetAlias"("assetId", "provider");

-- CreateIndex
CREATE UNIQUE INDEX "PriceSnapshot_assetId_timestamp_source_key" ON "PriceSnapshot"("assetId", "timestamp", "source");

-- CreateIndex
CREATE UNIQUE INDEX "Holding_symbol_accountId_key" ON "Holding"("symbol", "accountId");

-- CreateIndex
CREATE UNIQUE INDEX "ExchangeRate_fromCurrency_toCurrency_date_source_key" ON "ExchangeRate"("fromCurrency", "toCurrency", "date", "source");

-- CreateIndex
CREATE UNIQUE INDEX "ImportBatch_userId_accountId_checksum_key" ON "ImportBatch"("userId", "accountId", "checksum");

-- CreateIndex
CREATE UNIQUE INDEX "NetWorthSnapshot_userId_date_currency_key" ON "NetWorthSnapshot"("userId", "date", "currency");

-- CreateIndex
CREATE UNIQUE INDEX "PortfolioSnapshot_userId_timestamp_currency_granularity_key" ON "PortfolioSnapshot"("userId", "timestamp", "currency", "granularity");

-- CreateIndex
CREATE UNIQUE INDEX "PortfolioSnapshotItem_snapshotId_symbol_accountId_key" ON "PortfolioSnapshotItem"("snapshotId", "symbol", "accountId");

-- AddForeignKey
ALTER TABLE "Account" ADD CONSTRAINT "Account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountShare" ADD CONSTRAINT "AccountShare_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountShare" ADD CONSTRAINT "AccountShare_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccountShare" ADD CONSTRAINT "AccountShare_sharedWithId_fkey" FOREIGN KEY ("sharedWithId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

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
ALTER TABLE "BudgetItem" ADD CONSTRAINT "BudgetItem_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "Category"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAlert" ADD CONSTRAINT "BudgetAlert_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetAlert" ADD CONSTRAINT "BudgetAlert_budgetItemId_fkey" FOREIGN KEY ("budgetItemId") REFERENCES "BudgetItem"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssetAlias" ADD CONSTRAINT "AssetAlias_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PriceSnapshot" ADD CONSTRAINT "PriceSnapshot_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentTransaction" ADD CONSTRAINT "InvestmentTransaction_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentTransaction" ADD CONSTRAINT "InvestmentTransaction_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InvestmentTransaction" ADD CONSTRAINT "InvestmentTransaction_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "ImportBatch"("id") ON DELETE SET NULL ON UPDATE CASCADE;

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
ALTER TABLE "PortfolioSnapshot" ADD CONSTRAINT "PortfolioSnapshot_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PortfolioSnapshotItem" ADD CONSTRAINT "PortfolioSnapshotItem_snapshotId_fkey" FOREIGN KEY ("snapshotId") REFERENCES "PortfolioSnapshot"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PortfolioSnapshotItem" ADD CONSTRAINT "PortfolioSnapshotItem_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "Asset"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PortfolioSnapshotItem" ADD CONSTRAINT "PortfolioSnapshotItem_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
