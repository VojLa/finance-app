--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA "public";


--
-- Name: SCHEMA "public"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA "public" IS 'standard public schema';


--
-- Name: AccountInviteStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AccountInviteStatus" AS ENUM (
    'pending',
    'accepted',
    'revoked',
    'expired'
);


--
-- Name: AccountMemberRole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AccountMemberRole" AS ENUM (
    'owner',
    'admin',
    'viewer',
    'editor'
);


--
-- Name: AccountRelationType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AccountRelationType" AS ENUM (
    'owner',
    'joint_owner',
    'manager',
    'beneficiary',
    'collaborator'
);


--
-- Name: AccountType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AccountType" AS ENUM (
    'bank',
    'cash',
    'savings',
    'broker',
    'exchange',
    'crypto_wallet',
    'credit_card',
    'loan',
    'mortgage'
);


--
-- Name: AliasMatchType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AliasMatchType" AS ENUM (
    'exact',
    'contains',
    'starts_with',
    'ends_with'
);


--
-- Name: AssetAliasProvider; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AssetAliasProvider" AS ENUM (
    'coingecko',
    'yahoo_finance',
    'stooq',
    'twelve_data',
    'broker',
    'exchange'
);


--
-- Name: AssetType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."AssetType" AS ENUM (
    'stock',
    'etf',
    'crypto',
    'commodity',
    'cash',
    'bond',
    'other'
);


--
-- Name: BackgroundJobKind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."BackgroundJobKind" AS ENUM (
    'import_workflow'
);


--
-- Name: BackgroundJobStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."BackgroundJobStatus" AS ENUM (
    'queued',
    'running',
    'retry_wait',
    'completed',
    'failed'
);


--
-- Name: BudgetAlertType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."BudgetAlertType" AS ENUM (
    'approaching_limit',
    'exceeded',
    'reset'
);


--
-- Name: BudgetPeriodType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."BudgetPeriodType" AS ENUM (
    'monthly',
    'weekly',
    'yearly',
    'custom'
);


--
-- Name: CategoryType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."CategoryType" AS ENUM (
    'expense',
    'income',
    'both'
);


--
-- Name: CounterpartyType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."CounterpartyType" AS ENUM (
    'merchant',
    'family',
    'partner',
    'friend',
    'employer',
    'broker',
    'exchange',
    'bank',
    'service_provider',
    'other'
);


--
-- Name: ExchangeRateSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ExchangeRateSource" AS ENUM (
    'twelve_data',
    'cnb',
    'ecb',
    'manual',
    'broker',
    'exchange',
    'yahoo_finance'
);


--
-- Name: ImportLogEvent; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ImportLogEvent" AS ENUM (
    'started',
    'parse_error',
    'validation_failed',
    'dedup_skipped',
    'holdings_recalculated',
    'snapshots_recalculated',
    'snapshot_validation_failed',
    'completed',
    'failed'
);


--
-- Name: ImportLogLevel; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ImportLogLevel" AS ENUM (
    'info',
    'warning',
    'error'
);


--
-- Name: ImportRowStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ImportRowStatus" AS ENUM (
    'pending',
    'imported',
    'skipped',
    'duplicate',
    'failed',
    'needs_review'
);


--
-- Name: ImportSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ImportSource" AS ENUM (
    'raiffeisenbank',
    'trading212',
    'anycoin',
    'manual'
);


--
-- Name: ImportStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."ImportStatus" AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'partially_completed',
    'cancelled'
);


--
-- Name: InvestmentEventType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."InvestmentEventType" AS ENUM (
    'trade',
    'cash_deposit',
    'cash_withdrawal',
    'dividend',
    'interest',
    'currency_conversion',
    'asset_transfer',
    'fee',
    'staking_reward',
    'airdrop',
    'adjustment'
);


--
-- Name: InvestmentMovementKind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."InvestmentMovementKind" AS ENUM (
    'asset',
    'cash',
    'fee',
    'tax'
);


--
-- Name: LiabilityBalanceSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."LiabilityBalanceSource" AS ENUM (
    'manual',
    'statement',
    'provider',
    'import',
    'migration'
);


--
-- Name: MovementDirection; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."MovementDirection" AS ENUM (
    'in',
    'out'
);


--
-- Name: PriceSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."PriceSource" AS ENUM (
    'coingecko',
    'yahoo_finance',
    'stooq',
    'twelve_data',
    'manual',
    'broker',
    'exchange'
);


--
-- Name: RuleField; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."RuleField" AS ENUM (
    'description',
    'counterparty'
);


--
-- Name: RuleOperator; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."RuleOperator" AS ENUM (
    'contains',
    'equals',
    'starts_with',
    'ends_with',
    'greater_than',
    'less_than'
);


--
-- Name: SnapshotGranularity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."SnapshotGranularity" AS ENUM (
    'minute',
    'hour',
    'day',
    'week',
    'month'
);


--
-- Name: SnapshotSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."SnapshotSource" AS ENUM (
    'import_event',
    'price_refresh',
    'holdings_recalculation',
    'scheduled',
    'manual_recalculation'
);


--
-- Name: TransactionClassification; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."TransactionClassification" AS ENUM (
    'real_income',
    'real_expense',
    'internal_transfer',
    'investment_transfer',
    'loan_given',
    'loan_received',
    'loan_repayment',
    'refund',
    'cash_exchange',
    'credit_card_payment',
    'ignored',
    'needs_review'
);


--
-- Name: TransactionType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."TransactionType" AS ENUM (
    'income',
    'expense',
    'transfer'
);


--
-- Name: initializeAccountCanonicalState(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION "public"."initializeAccountCanonicalState"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
            BEGIN
                INSERT INTO "public"."AccountCanonicalState"
                    ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
                VALUES (NEW."id", 0, 0, NULL, NEW."updatedAt");
                RETURN NEW;
            END;
            $$;


SET default_tablespace = '';

SET default_table_access_method = "heap";

--
-- Name: Account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Account" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "type" "public"."AccountType" NOT NULL,
    "currency" "text" NOT NULL,
    "color" "text",
    "isArchived" boolean DEFAULT false NOT NULL,
    "archivedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "notes" "text"
);


--
-- Name: AccountCanonicalChange; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountCanonicalChange" (
    "accountId" "text" NOT NULL,
    "revision" bigint NOT NULL,
    "kind" "text" NOT NULL,
    "entityId" "text" NOT NULL,
    "financialTimestamp" timestamp(3) without time zone NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "AccountCanonicalChange_kind_supported" CHECK (("kind" = ANY (ARRAY['transaction'::"text", 'investment_event'::"text", 'liability_balance'::"text"]))),
    CONSTRAINT "AccountCanonicalChange_revision_positive" CHECK (("revision" > 0))
);


--
-- Name: AccountCanonicalState; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountCanonicalState" (
    "accountId" "text" NOT NULL,
    "lastRevision" bigint DEFAULT 0 NOT NULL,
    "lastInvestmentRevision" bigint DEFAULT 0 NOT NULL,
    "holdingRevision" bigint,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "AccountCanonicalState_holdingRevision_nonnegative" CHECK ((("holdingRevision" IS NULL) OR ("holdingRevision" >= 0))),
    CONSTRAINT "AccountCanonicalState_holding_not_after_investment" CHECK ((("holdingRevision" IS NULL) OR ("holdingRevision" <= "lastInvestmentRevision"))),
    CONSTRAINT "AccountCanonicalState_investment_not_after_last" CHECK (("lastInvestmentRevision" <= "lastRevision")),
    CONSTRAINT "AccountCanonicalState_lastInvestmentRevision_nonnegative" CHECK (("lastInvestmentRevision" >= 0)),
    CONSTRAINT "AccountCanonicalState_lastRevision_nonnegative" CHECK (("lastRevision" >= 0))
);


--
-- Name: AccountInvite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountInvite" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "inviterId" "text" NOT NULL,
    "acceptedById" "text",
    "email" "text" NOT NULL,
    "role" "public"."AccountMemberRole" DEFAULT 'viewer'::"public"."AccountMemberRole" NOT NULL,
    "status" "public"."AccountInviteStatus" DEFAULT 'pending'::"public"."AccountInviteStatus" NOT NULL,
    "tokenHash" "text" NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "acceptedAt" timestamp(3) without time zone,
    "revokedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: AccountMember; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountMember" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "role" "public"."AccountMemberRole" DEFAULT 'viewer'::"public"."AccountMemberRole" NOT NULL,
    "relationType" "public"."AccountRelationType" DEFAULT 'owner'::"public"."AccountRelationType" NOT NULL,
    "invitedById" "text",
    "acceptedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: AccountSnapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountSnapshot" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "source" "public"."SnapshotSource" NOT NULL,
    "currency" "text" DEFAULT 'CZK'::"text" NOT NULL,
    "cashValue" numeric(18,6) NOT NULL,
    "investmentValue" numeric(18,6) NOT NULL,
    "investmentCostBasis" numeric(18,6) DEFAULT 0 NOT NULL,
    "liabilitiesValue" numeric(18,6) NOT NULL,
    "totalValue" numeric(18,6) NOT NULL,
    "isRecalculated" boolean DEFAULT false NOT NULL,
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "calculationVersion" integer DEFAULT 1 NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "netDepositsValue" numeric(18,6) DEFAULT 0 NOT NULL,
    "realizedPnlValue" numeric(18,6) DEFAULT 0 NOT NULL,
    "unrealizedPnlValue" numeric(18,6) DEFAULT 0 NOT NULL,
    "feesValue" numeric(18,6) DEFAULT 0 NOT NULL,
    "taxesValue" numeric(18,6) DEFAULT 0 NOT NULL,
    "cashValueByCurrency" "jsonb",
    "investmentValueByCurrency" "jsonb",
    "investmentCostBasisByCurrency" "jsonb",
    "netDepositsByCurrency" "jsonb",
    "realizedPnlByCurrency" "jsonb",
    "unrealizedPnlByCurrency" "jsonb",
    "feesByCurrency" "jsonb",
    "taxesByCurrency" "jsonb",
    "exchangeRates" "jsonb"
);


--
-- Name: AccountSnapshotCanonicalBoundary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountSnapshotCanonicalBoundary" (
    "snapshotId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "canonicalRevision" bigint NOT NULL,
    "investmentRevision" bigint,
    "holdingRevision" bigint,
    "selectedLiabilityBalanceId" "text",
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "AccountSnapshotCanonicalBoundary_canonical_nonnegative" CHECK (("canonicalRevision" >= 0)),
    CONSTRAINT "AccountSnapshotCanonicalBoundary_holding_fresh" CHECK ((("investmentRevision" IS NULL) OR ("investmentRevision" = "holdingRevision"))),
    CONSTRAINT "AccountSnapshotCanonicalBoundary_holding_nonnegative" CHECK ((("holdingRevision" IS NULL) OR ("holdingRevision" >= 0))),
    CONSTRAINT "AccountSnapshotCanonicalBoundary_investment_holding_pair" CHECK ((("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))),
    CONSTRAINT "AccountSnapshotCanonicalBoundary_investment_nonnegative" CHECK ((("investmentRevision" IS NULL) OR ("investmentRevision" >= 0))),
    CONSTRAINT "AccountSnapshotCanonicalBoundary_investment_not_after_canonical" CHECK ((("investmentRevision" IS NULL) OR ("investmentRevision" <= "canonicalRevision")))
);


--
-- Name: AccountSnapshotItem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AccountSnapshotItem" (
    "id" "text" NOT NULL,
    "snapshotId" "text" NOT NULL,
    "assetId" "text",
    "listingId" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "pricePerUnit" numeric(28,10) NOT NULL,
    "priceCurrency" "text",
    "priceSource" "public"."PriceSource",
    "priceTimestamp" timestamp(3) without time zone,
    "value" numeric(18,6) NOT NULL,
    "costBasis" numeric(28,10),
    "costCurrency" "text",
    "allocationPct" numeric(8,4) NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "nativeValue" numeric(28,10),
    "valueCurrency" "text",
    "nativeCostBasis" numeric(28,10),
    "nativeCostCurrency" "text",
    "nativeCostBasisByCurrency" "jsonb" NOT NULL,
    "averageBuyPrice" numeric(28,10) NOT NULL,
    "averageBuyPriceCurrency" "text" NOT NULL,
    CONSTRAINT "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object" CHECK ((("jsonb_typeof"("nativeCostBasisByCurrency") = 'object'::"text") AND ("nativeCostBasisByCurrency" <> '{}'::"jsonb")))
);


--
-- Name: Asset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Asset" (
    "id" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "isin" "text",
    "name" "text",
    "assetType" "public"."AssetType" NOT NULL,
    "currency" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: AssetAlias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AssetAlias" (
    "id" "text" NOT NULL,
    "assetId" "text" NOT NULL,
    "provider" "public"."AssetAliasProvider" NOT NULL,
    "externalId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: AssetListing; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."AssetListing" (
    "id" "text" NOT NULL,
    "assetId" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "exchange" "text",
    "mic" "text",
    "currency" "text" NOT NULL,
    "country" "text",
    "provider" "public"."PriceSource",
    "providerSymbol" "text",
    "isPrimary" boolean DEFAULT false NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: BackgroundJob; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."BackgroundJob" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "kind" "public"."BackgroundJobKind" NOT NULL,
    "status" "public"."BackgroundJobStatus" DEFAULT 'queued'::"public"."BackgroundJobStatus" NOT NULL,
    "idempotencyKey" "text" NOT NULL,
    "payload" "jsonb" NOT NULL,
    "checkpoint" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "progress" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "result" "jsonb",
    "errorCode" "text",
    "errorMessage" "text",
    "attemptCount" integer DEFAULT 0 NOT NULL,
    "manualRetryCount" integer DEFAULT 0 NOT NULL,
    "maxAttempts" integer DEFAULT 3 NOT NULL,
    "runAfter" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "leaseOwner" "text",
    "leaseVersion" integer DEFAULT 0 NOT NULL,
    "leaseExpiresAt" timestamp(3) without time zone,
    "leaseHeartbeatAt" timestamp(3) without time zone,
    "startedAt" timestamp(3) without time zone,
    "finishedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "BackgroundJob_attemptCount_nonnegative" CHECK (("attemptCount" >= 0)),
    CONSTRAINT "BackgroundJob_attemptCount_within_maximum" CHECK (("attemptCount" <= "maxAttempts")),
    CONSTRAINT "BackgroundJob_checkpoint_bounded" CHECK (("octet_length"(("checkpoint")::"text") <= 65536)),
    CONSTRAINT "BackgroundJob_checkpoint_object" CHECK (("jsonb_typeof"("checkpoint") = 'object'::"text")),
    CONSTRAINT "BackgroundJob_completed_has_no_error" CHECK ((("status" <> 'completed'::"public"."BackgroundJobStatus") OR (("errorCode" IS NULL) AND ("errorMessage" IS NULL)))),
    CONSTRAINT "BackgroundJob_completed_has_result" CHECK ((("status" = 'completed'::"public"."BackgroundJobStatus") = ("result" IS NOT NULL))),
    CONSTRAINT "BackgroundJob_errorCode_bounded" CHECK ((("errorCode" IS NULL) OR (("char_length"("errorCode") >= 1) AND ("char_length"("errorCode") <= 100)))),
    CONSTRAINT "BackgroundJob_errorMessage_bounded" CHECK ((("errorMessage" IS NULL) OR (("char_length"("errorMessage") >= 1) AND ("char_length"("errorMessage") <= 1000)))),
    CONSTRAINT "BackgroundJob_error_pair_complete" CHECK (((("errorCode" IS NULL) AND ("errorMessage" IS NULL)) OR (("errorCode" IS NOT NULL) AND ("errorMessage" IS NOT NULL)))),
    CONSTRAINT "BackgroundJob_failed_has_safe_error" CHECK ((("status" <> 'failed'::"public"."BackgroundJobStatus") OR (("errorCode" IS NOT NULL) AND ("errorMessage" IS NOT NULL)))),
    CONSTRAINT "BackgroundJob_idempotencyKey_bounded" CHECK ((("char_length"("idempotencyKey") >= 1) AND ("char_length"("idempotencyKey") <= 200))),
    CONSTRAINT "BackgroundJob_leaseOwner_bounded" CHECK ((("leaseOwner" IS NULL) OR (("char_length"("leaseOwner") >= 1) AND ("char_length"("leaseOwner") <= 200)))),
    CONSTRAINT "BackgroundJob_leaseVersion_nonnegative" CHECK (("leaseVersion" >= 0)),
    CONSTRAINT "BackgroundJob_lease_complete_or_absent" CHECK (((("leaseOwner" IS NULL) AND ("leaseExpiresAt" IS NULL) AND ("leaseHeartbeatAt" IS NULL)) OR (("leaseOwner" IS NOT NULL) AND ("leaseExpiresAt" IS NOT NULL) AND ("leaseHeartbeatAt" IS NOT NULL)))),
    CONSTRAINT "BackgroundJob_manualRetryCount_nonnegative" CHECK (("manualRetryCount" >= 0)),
    CONSTRAINT "BackgroundJob_maxAttempts_bounded" CHECK ((("maxAttempts" >= 1) AND ("maxAttempts" <= 20))),
    CONSTRAINT "BackgroundJob_payload_bounded" CHECK (("octet_length"(("payload")::"text") <= 65536)),
    CONSTRAINT "BackgroundJob_payload_object" CHECK ((("jsonb_typeof"("payload") = 'object'::"text") AND ("payload" <> '{}'::"jsonb"))),
    CONSTRAINT "BackgroundJob_progress_bounded" CHECK (("octet_length"(("progress")::"text") <= 16384)),
    CONSTRAINT "BackgroundJob_progress_object" CHECK (("jsonb_typeof"("progress") = 'object'::"text")),
    CONSTRAINT "BackgroundJob_result_bounded" CHECK ((("result" IS NULL) OR ("octet_length"(("result")::"text") <= 65536))),
    CONSTRAINT "BackgroundJob_result_object" CHECK ((("result" IS NULL) OR ("jsonb_typeof"("result") = 'object'::"text"))),
    CONSTRAINT "BackgroundJob_running_has_lease" CHECK ((("status" = 'running'::"public"."BackgroundJobStatus") = ("leaseOwner" IS NOT NULL))),
    CONSTRAINT "BackgroundJob_terminal_has_finishedAt" CHECK ((("status" = ANY (ARRAY['completed'::"public"."BackgroundJobStatus", 'failed'::"public"."BackgroundJobStatus"])) = ("finishedAt" IS NOT NULL)))
);


--
-- Name: Budget; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Budget" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "periodStart" timestamp(3) without time zone NOT NULL,
    "periodEnd" timestamp(3) without time zone NOT NULL,
    "periodType" "public"."BudgetPeriodType" DEFAULT 'monthly'::"public"."BudgetPeriodType" NOT NULL,
    "currency" "text" DEFAULT 'CZK'::"text" NOT NULL,
    "rolloverEnabled" boolean DEFAULT false NOT NULL,
    "userId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: BudgetAccount; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."BudgetAccount" (
    "id" "text" NOT NULL,
    "budgetId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: BudgetAlert; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."BudgetAlert" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "budgetItemId" "text" NOT NULL,
    "type" "public"."BudgetAlertType" NOT NULL,
    "threshold" numeric(5,4) NOT NULL,
    "triggeredAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "acknowledgedAt" timestamp(3) without time zone
);


--
-- Name: BudgetItem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."BudgetItem" (
    "id" "text" NOT NULL,
    "name" "text",
    "amount" numeric(18,6) NOT NULL,
    "currency" "text" DEFAULT 'CZK'::"text" NOT NULL,
    "rolloverAmount" numeric(18,6),
    "budgetId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: BudgetItemCategory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."BudgetItemCategory" (
    "id" "text" NOT NULL,
    "budgetItemId" "text" NOT NULL,
    "categoryId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: Category; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Category" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "icon" "text",
    "color" "text",
    "type" "public"."CategoryType" NOT NULL,
    "parentId" "text",
    "isDefault" boolean DEFAULT false NOT NULL,
    "userId" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: CategoryRule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."CategoryRule" (
    "id" "text" NOT NULL,
    "value" "text" NOT NULL,
    "field" "public"."RuleField" NOT NULL,
    "operator" "public"."RuleOperator" DEFAULT 'contains'::"public"."RuleOperator" NOT NULL,
    "classification" "public"."TransactionClassification",
    "requiresReview" boolean DEFAULT false NOT NULL,
    "priority" integer DEFAULT 0 NOT NULL,
    "userId" "text",
    "categoryId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: Counterparty; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Counterparty" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "name" "text" NOT NULL,
    "type" "public"."CounterpartyType" DEFAULT 'other'::"public"."CounterpartyType" NOT NULL,
    "accountNumber" "text",
    "iban" "text",
    "notes" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: CounterpartyAlias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."CounterpartyAlias" (
    "id" "text" NOT NULL,
    "counterpartyId" "text" NOT NULL,
    "alias" "text" NOT NULL,
    "matchType" "public"."AliasMatchType" DEFAULT 'contains'::"public"."AliasMatchType" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: DailySnapshotBaseline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."DailySnapshotBaseline" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "netWorthSnapshotId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "currency" "text" NOT NULL,
    "calculationVersion" integer NOT NULL,
    "source" "public"."SnapshotSource" NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "DailySnapshotBaseline_calculationVersion_positive" CHECK (("calculationVersion" > 0)),
    CONSTRAINT "DailySnapshotBaseline_day_only" CHECK (("granularity" = 'day'::"public"."SnapshotGranularity"))
);


--
-- Name: DailySnapshotBaselineAccount; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."DailySnapshotBaselineAccount" (
    "baselineId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "accountType" "public"."AccountType" NOT NULL,
    "accountCurrency" "text" NOT NULL,
    "primarySnapshotId" "text" NOT NULL,
    "presentationSnapshotId" "text" NOT NULL,
    "canonicalRevision" bigint NOT NULL,
    "investmentRevision" bigint,
    "holdingRevision" bigint,
    "selectedLiabilityBalanceId" "text",
    CONSTRAINT "DailySnapshotBaselineAccount_canonical_nonnegative" CHECK (("canonicalRevision" >= 0)),
    CONSTRAINT "DailySnapshotBaselineAccount_holding_fresh" CHECK ((("investmentRevision" IS NULL) OR ("investmentRevision" = "holdingRevision"))),
    CONSTRAINT "DailySnapshotBaselineAccount_holding_nonnegative" CHECK ((("holdingRevision" IS NULL) OR ("holdingRevision" >= 0))),
    CONSTRAINT "DailySnapshotBaselineAccount_investment_holding_pair" CHECK ((("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))),
    CONSTRAINT "DailySnapshotBaselineAccount_investment_nonnegative" CHECK ((("investmentRevision" IS NULL) OR ("investmentRevision" >= 0)))
);


--
-- Name: ExchangeRate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ExchangeRate" (
    "id" "text" NOT NULL,
    "fromCurrency" "text" NOT NULL,
    "toCurrency" "text" NOT NULL,
    "rate" numeric(18,8) NOT NULL,
    "date" timestamp(3) without time zone NOT NULL,
    "source" "public"."ExchangeRateSource" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: Holding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Holding" (
    "id" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "name" "text",
    "assetType" "public"."AssetType" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "avgBuyPrice" numeric(28,10) NOT NULL,
    "currency" "text" NOT NULL,
    "currentPrice" numeric(28,10),
    "currentValue" numeric(28,10),
    "unrealizedPnl" numeric(28,10),
    "realizedPnl" numeric(28,10),
    "assetId" "text",
    "listingId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "costBasisByCurrency" "jsonb" NOT NULL,
    CONSTRAINT "Holding_costBasisByCurrency_nonempty_object" CHECK ((("jsonb_typeof"("costBasisByCurrency") = 'object'::"text") AND ("costBasisByCurrency" <> '{}'::"jsonb")))
);


--
-- Name: ImportBatch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportBatch" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "source" "public"."ImportSource" NOT NULL,
    "filename" "text" NOT NULL,
    "fileSize" integer,
    "fileEncoding" "text",
    "checksum" "text" NOT NULL,
    "status" "public"."ImportStatus" DEFAULT 'completed'::"public"."ImportStatus" NOT NULL,
    "rowsTotal" integer,
    "rowsImported" integer,
    "rowsSkipped" integer,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "completedAt" timestamp(3) without time zone,
    "retainUntil" timestamp(3) without time zone,
    "rawDataPurgedAt" timestamp(3) without time zone
);


--
-- Name: ImportLog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportLog" (
    "id" "text" NOT NULL,
    "importBatchId" "text" NOT NULL,
    "level" "public"."ImportLogLevel" NOT NULL,
    "event" "public"."ImportLogEvent" NOT NULL,
    "message" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ImportRow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportRow" (
    "id" "text" NOT NULL,
    "importBatchId" "text" NOT NULL,
    "rowNumber" integer NOT NULL,
    "rawData" "jsonb" NOT NULL,
    "normalizedData" "jsonb",
    "validationErrors" "jsonb",
    "deduplicationKey" "text",
    "status" "public"."ImportRowStatus" DEFAULT 'pending'::"public"."ImportRowStatus" NOT NULL,
    "errorMessage" "text",
    "createdTransactionId" "text",
    "createdInvestmentEventId" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: InvestmentEvent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."InvestmentEvent" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "type" "public"."InvestmentEventType" NOT NULL,
    "date" timestamp(3) without time zone NOT NULL,
    "source" "public"."ImportSource",
    "externalId" "text",
    "orderId" "text",
    "description" "text",
    "realizedPnl" numeric(28,10),
    "realizedPnlCurrency" "text",
    "importBatchId" "text",
    "archivedAt" timestamp(3) without time zone,
    "deletedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: InvestmentMovement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."InvestmentMovement" (
    "id" "text" NOT NULL,
    "eventId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "assetId" "text",
    "listingId" "text",
    "kind" "public"."InvestmentMovementKind" NOT NULL,
    "direction" "public"."MovementDirection" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "currency" "text" NOT NULL,
    "pricePerUnit" numeric(28,10),
    "valueAmount" numeric(28,10),
    "valueCurrency" "text",
    "sourceSymbol" "text",
    "sourceAssetType" "public"."AssetType",
    "note" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: LiabilityBalance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."LiabilityBalance" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "effectiveAt" timestamp(3) without time zone NOT NULL,
    "currency" "text" NOT NULL,
    "outstandingPrincipal" numeric(18,6) NOT NULL,
    "accruedInterest" numeric(18,6) NOT NULL,
    "feesOutstanding" numeric(18,6) NOT NULL,
    "totalOutstanding" numeric(18,6) NOT NULL,
    "source" "public"."LiabilityBalanceSource" NOT NULL,
    "externalId" "text",
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "LiabilityBalance_accruedInterest_nonnegative" CHECK (("accruedInterest" >= (0)::numeric)),
    CONSTRAINT "LiabilityBalance_feesOutstanding_nonnegative" CHECK (("feesOutstanding" >= (0)::numeric)),
    CONSTRAINT "LiabilityBalance_outstandingPrincipal_nonnegative" CHECK (("outstandingPrincipal" >= (0)::numeric)),
    CONSTRAINT "LiabilityBalance_totalOutstanding_components" CHECK (("totalOutstanding" = (("outstandingPrincipal" + "accruedInterest") + "feesOutstanding"))),
    CONSTRAINT "LiabilityBalance_totalOutstanding_nonnegative" CHECK (("totalOutstanding" >= (0)::numeric))
);


--
-- Name: NetWorthSnapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."NetWorthSnapshot" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "source" "public"."SnapshotSource" NOT NULL,
    "currency" "text" DEFAULT 'CZK'::"text" NOT NULL,
    "cashValue" numeric(18,6) NOT NULL,
    "portfolioValue" numeric(18,6) NOT NULL,
    "liabilitiesValue" numeric(18,6) NOT NULL,
    "totalNetWorth" numeric(18,6) NOT NULL,
    "isRecalculated" boolean DEFAULT false NOT NULL,
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "calculationVersion" integer DEFAULT 1 NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "cashValueByCurrency" "jsonb",
    "portfolioValueByCurrency" "jsonb",
    "liabilitiesValueByCurrency" "jsonb",
    "totalNetWorthByCurrency" "jsonb",
    "exchangeRates" "jsonb"
);


--
-- Name: PriceSnapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."PriceSnapshot" (
    "id" "text" NOT NULL,
    "assetId" "text" NOT NULL,
    "listingId" "text" NOT NULL,
    "price" numeric(28,10) NOT NULL,
    "currency" "text" NOT NULL,
    "source" "public"."PriceSource" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: Transaction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."Transaction" (
    "id" "text" NOT NULL,
    "date" timestamp(3) without time zone NOT NULL,
    "bookingDate" timestamp(3) without time zone,
    "amount" numeric(18,6) NOT NULL,
    "currency" "text" NOT NULL,
    "reportingAmount" numeric(18,6),
    "reportingCurrency" "text",
    "type" "public"."TransactionType" NOT NULL,
    "classification" "public"."TransactionClassification",
    "description" "text",
    "note" "text",
    "counterparty" "text",
    "externalId" "text",
    "isReviewed" boolean DEFAULT false NOT NULL,
    "archivedAt" timestamp(3) without time zone,
    "deletedAt" timestamp(3) without time zone,
    "categoryId" "text",
    "accountId" "text" NOT NULL,
    "importBatchId" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: TransactionPair; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."TransactionPair" (
    "id" "text" NOT NULL,
    "fromTransactionId" "text" NOT NULL,
    "toTransactionId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: TransactionSplit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."TransactionSplit" (
    "id" "text" NOT NULL,
    "transactionId" "text" NOT NULL,
    "categoryId" "text",
    "amount" numeric(18,6) NOT NULL,
    "currency" "text" NOT NULL,
    "note" "text",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: User; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."User" (
    "id" "text" NOT NULL,
    "email" "text" NOT NULL,
    "name" "text",
    "passwordHash" "text",
    "baseCurrency" "text" DEFAULT 'CZK'::"text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: AccountCanonicalChange AccountCanonicalChange_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountCanonicalChange"
    ADD CONSTRAINT "AccountCanonicalChange_pkey" PRIMARY KEY ("accountId", "revision");


--
-- Name: AccountCanonicalState AccountCanonicalState_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountCanonicalState"
    ADD CONSTRAINT "AccountCanonicalState_pkey" PRIMARY KEY ("accountId");


--
-- Name: AccountInvite AccountInvite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountInvite"
    ADD CONSTRAINT "AccountInvite_pkey" PRIMARY KEY ("id");


--
-- Name: AccountMember AccountMember_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountMember"
    ADD CONSTRAINT "AccountMember_pkey" PRIMARY KEY ("id");


--
-- Name: AccountSnapshotCanonicalBoundary AccountSnapshotCanonicalBoundary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotCanonicalBoundary"
    ADD CONSTRAINT "AccountSnapshotCanonicalBoundary_pkey" PRIMARY KEY ("snapshotId");


--
-- Name: AccountSnapshotItem AccountSnapshotItem_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotItem"
    ADD CONSTRAINT "AccountSnapshotItem_pkey" PRIMARY KEY ("id");


--
-- Name: AccountSnapshot AccountSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshot"
    ADD CONSTRAINT "AccountSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: Account Account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Account"
    ADD CONSTRAINT "Account_pkey" PRIMARY KEY ("id");


--
-- Name: AssetAlias AssetAlias_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetAlias"
    ADD CONSTRAINT "AssetAlias_pkey" PRIMARY KEY ("id");


--
-- Name: AssetListing AssetListing_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetListing"
    ADD CONSTRAINT "AssetListing_pkey" PRIMARY KEY ("id");


--
-- Name: Asset Asset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Asset"
    ADD CONSTRAINT "Asset_pkey" PRIMARY KEY ("id");


--
-- Name: BackgroundJob BackgroundJob_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BackgroundJob"
    ADD CONSTRAINT "BackgroundJob_pkey" PRIMARY KEY ("id");


--
-- Name: BudgetAccount BudgetAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAccount"
    ADD CONSTRAINT "BudgetAccount_pkey" PRIMARY KEY ("id");


--
-- Name: BudgetAlert BudgetAlert_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAlert"
    ADD CONSTRAINT "BudgetAlert_pkey" PRIMARY KEY ("id");


--
-- Name: BudgetItemCategory BudgetItemCategory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetItemCategory"
    ADD CONSTRAINT "BudgetItemCategory_pkey" PRIMARY KEY ("id");


--
-- Name: BudgetItem BudgetItem_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetItem"
    ADD CONSTRAINT "BudgetItem_pkey" PRIMARY KEY ("id");


--
-- Name: Budget Budget_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Budget"
    ADD CONSTRAINT "Budget_pkey" PRIMARY KEY ("id");


--
-- Name: CategoryRule CategoryRule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."CategoryRule"
    ADD CONSTRAINT "CategoryRule_pkey" PRIMARY KEY ("id");


--
-- Name: Category Category_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Category"
    ADD CONSTRAINT "Category_pkey" PRIMARY KEY ("id");


--
-- Name: CounterpartyAlias CounterpartyAlias_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."CounterpartyAlias"
    ADD CONSTRAINT "CounterpartyAlias_pkey" PRIMARY KEY ("id");


--
-- Name: Counterparty Counterparty_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Counterparty"
    ADD CONSTRAINT "Counterparty_pkey" PRIMARY KEY ("id");


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_pkey" PRIMARY KEY ("baselineId", "accountId");


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_pkey" PRIMARY KEY ("id");


--
-- Name: ExchangeRate ExchangeRate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ExchangeRate"
    ADD CONSTRAINT "ExchangeRate_pkey" PRIMARY KEY ("id");


--
-- Name: Holding Holding_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Holding"
    ADD CONSTRAINT "Holding_pkey" PRIMARY KEY ("id");


--
-- Name: ImportBatch ImportBatch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportBatch"
    ADD CONSTRAINT "ImportBatch_pkey" PRIMARY KEY ("id");


--
-- Name: ImportLog ImportLog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportLog"
    ADD CONSTRAINT "ImportLog_pkey" PRIMARY KEY ("id");


--
-- Name: ImportRow ImportRow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportRow"
    ADD CONSTRAINT "ImportRow_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentEvent InvestmentEvent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentEvent"
    ADD CONSTRAINT "InvestmentEvent_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentMovement InvestmentMovement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovement"
    ADD CONSTRAINT "InvestmentMovement_pkey" PRIMARY KEY ("id");


--
-- Name: LiabilityBalance LiabilityBalance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."LiabilityBalance"
    ADD CONSTRAINT "LiabilityBalance_pkey" PRIMARY KEY ("id");


--
-- Name: NetWorthSnapshot NetWorthSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: PriceSnapshot PriceSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PriceSnapshot"
    ADD CONSTRAINT "PriceSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: TransactionPair TransactionPair_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionPair"
    ADD CONSTRAINT "TransactionPair_pkey" PRIMARY KEY ("id");


--
-- Name: TransactionSplit TransactionSplit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionSplit"
    ADD CONSTRAINT "TransactionSplit_pkey" PRIMARY KEY ("id");


--
-- Name: Transaction Transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Transaction"
    ADD CONSTRAINT "Transaction_pkey" PRIMARY KEY ("id");


--
-- Name: User User_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."User"
    ADD CONSTRAINT "User_pkey" PRIMARY KEY ("id");


--
-- Name: AccountCanonicalChange_account_financial_revision_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountCanonicalChange_account_financial_revision_idx" ON "public"."AccountCanonicalChange" USING "btree" ("accountId", "financialTimestamp", "revision");


--
-- Name: AccountCanonicalChange_kind_entityId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountCanonicalChange_kind_entityId_key" ON "public"."AccountCanonicalChange" USING "btree" ("kind", "entityId");


--
-- Name: AccountInvite_accountId_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountInvite_accountId_status_idx" ON "public"."AccountInvite" USING "btree" ("accountId", "status");


--
-- Name: AccountInvite_email_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountInvite_email_status_idx" ON "public"."AccountInvite" USING "btree" ("email", "status");


--
-- Name: AccountInvite_inviterId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountInvite_inviterId_createdAt_idx" ON "public"."AccountInvite" USING "btree" ("inviterId", "createdAt");


--
-- Name: AccountInvite_tokenHash_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountInvite_tokenHash_key" ON "public"."AccountInvite" USING "btree" ("tokenHash");


--
-- Name: AccountMember_accountId_role_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountMember_accountId_role_idx" ON "public"."AccountMember" USING "btree" ("accountId", "role");


--
-- Name: AccountMember_accountId_userId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountMember_accountId_userId_key" ON "public"."AccountMember" USING "btree" ("accountId", "userId");


--
-- Name: AccountMember_userId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountMember_userId_idx" ON "public"."AccountMember" USING "btree" ("userId");


--
-- Name: AccountSnapshotBoundary_account_canonicalRevision_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshotBoundary_account_canonicalRevision_idx" ON "public"."AccountSnapshotCanonicalBoundary" USING "btree" ("accountId", "canonicalRevision");


--
-- Name: AccountSnapshotItem_assetId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshotItem_assetId_idx" ON "public"."AccountSnapshotItem" USING "btree" ("assetId");


--
-- Name: AccountSnapshotItem_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshotItem_listingId_idx" ON "public"."AccountSnapshotItem" USING "btree" ("listingId");


--
-- Name: AccountSnapshotItem_snapshotId_listingId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountSnapshotItem_snapshotId_listingId_key" ON "public"."AccountSnapshotItem" USING "btree" ("snapshotId", "listingId");


--
-- Name: AccountSnapshot_accountId_granularity_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshot_accountId_granularity_timestamp_idx" ON "public"."AccountSnapshot" USING "btree" ("accountId", "granularity", "timestamp");


--
-- Name: AccountSnapshot_accountId_timestamp_currency_granularity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountSnapshot_accountId_timestamp_currency_granularity_key" ON "public"."AccountSnapshot" USING "btree" ("accountId", "timestamp", "currency", "granularity");


--
-- Name: AccountSnapshot_source_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshot_source_timestamp_idx" ON "public"."AccountSnapshot" USING "btree" ("source", "timestamp");


--
-- Name: Account_isArchived_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Account_isArchived_idx" ON "public"."Account" USING "btree" ("isArchived");


--
-- Name: Account_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Account_type_idx" ON "public"."Account" USING "btree" ("type");


--
-- Name: AssetAlias_assetId_provider_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AssetAlias_assetId_provider_idx" ON "public"."AssetAlias" USING "btree" ("assetId", "provider");


--
-- Name: AssetAlias_provider_externalId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetAlias_provider_externalId_key" ON "public"."AssetAlias" USING "btree" ("provider", "externalId");


--
-- Name: AssetListing_assetId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AssetListing_assetId_idx" ON "public"."AssetListing" USING "btree" ("assetId");


--
-- Name: AssetListing_assetId_symbol_exchange_currency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetListing_assetId_symbol_exchange_currency_key" ON "public"."AssetListing" USING "btree" ("assetId", "symbol", "exchange", "currency");


--
-- Name: AssetListing_provider_providerSymbol_currency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetListing_provider_providerSymbol_currency_key" ON "public"."AssetListing" USING "btree" ("provider", "providerSymbol", "currency");


--
-- Name: AssetListing_provider_providerSymbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AssetListing_provider_providerSymbol_idx" ON "public"."AssetListing" USING "btree" ("provider", "providerSymbol");


--
-- Name: AssetListing_symbol_exchange_currency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetListing_symbol_exchange_currency_key" ON "public"."AssetListing" USING "btree" ("symbol", "exchange", "currency");


--
-- Name: AssetListing_symbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AssetListing_symbol_idx" ON "public"."AssetListing" USING "btree" ("symbol");


--
-- Name: Asset_assetType_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Asset_assetType_idx" ON "public"."Asset" USING "btree" ("assetType");


--
-- Name: Asset_isin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Asset_isin_idx" ON "public"."Asset" USING "btree" ("isin");


--
-- Name: Asset_symbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Asset_symbol_idx" ON "public"."Asset" USING "btree" ("symbol");


--
-- Name: BackgroundJob_accountId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BackgroundJob_accountId_createdAt_idx" ON "public"."BackgroundJob" USING "btree" ("accountId", "createdAt");


--
-- Name: BackgroundJob_claim_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BackgroundJob_claim_idx" ON "public"."BackgroundJob" USING "btree" ("status", "runAfter", "leaseExpiresAt", "createdAt") WHERE ("status" = ANY (ARRAY['queued'::"public"."BackgroundJobStatus", 'retry_wait'::"public"."BackgroundJobStatus"]));


--
-- Name: BackgroundJob_expiredLease_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BackgroundJob_expiredLease_idx" ON "public"."BackgroundJob" USING "btree" ("leaseExpiresAt") WHERE ("status" = 'running'::"public"."BackgroundJobStatus");


--
-- Name: BackgroundJob_one_running_per_account_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_one_running_per_account_key" ON "public"."BackgroundJob" USING "btree" ("accountId") WHERE ("status" = 'running'::"public"."BackgroundJobStatus");


--
-- Name: BackgroundJob_userId_accountId_kind_idempotencyKey_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_userId_accountId_kind_idempotencyKey_key" ON "public"."BackgroundJob" USING "btree" ("userId", "accountId", "kind", "idempotencyKey");


--
-- Name: BackgroundJob_userId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BackgroundJob_userId_createdAt_idx" ON "public"."BackgroundJob" USING "btree" ("userId", "createdAt");


--
-- Name: BudgetAccount_accountId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BudgetAccount_accountId_idx" ON "public"."BudgetAccount" USING "btree" ("accountId");


--
-- Name: BudgetAccount_budgetId_accountId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BudgetAccount_budgetId_accountId_key" ON "public"."BudgetAccount" USING "btree" ("budgetId", "accountId");


--
-- Name: BudgetAlert_budgetItemId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BudgetAlert_budgetItemId_idx" ON "public"."BudgetAlert" USING "btree" ("budgetItemId");


--
-- Name: BudgetAlert_userId_triggeredAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BudgetAlert_userId_triggeredAt_idx" ON "public"."BudgetAlert" USING "btree" ("userId", "triggeredAt");


--
-- Name: BudgetItemCategory_budgetItemId_categoryId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BudgetItemCategory_budgetItemId_categoryId_key" ON "public"."BudgetItemCategory" USING "btree" ("budgetItemId", "categoryId");


--
-- Name: BudgetItemCategory_categoryId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BudgetItemCategory_categoryId_idx" ON "public"."BudgetItemCategory" USING "btree" ("categoryId");


--
-- Name: BudgetItem_budgetId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "BudgetItem_budgetId_idx" ON "public"."BudgetItem" USING "btree" ("budgetId");


--
-- Name: Budget_userId_periodStart_periodEnd_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Budget_userId_periodStart_periodEnd_idx" ON "public"."Budget" USING "btree" ("userId", "periodStart", "periodEnd");


--
-- Name: Budget_userId_periodStart_periodEnd_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "Budget_userId_periodStart_periodEnd_name_key" ON "public"."Budget" USING "btree" ("userId", "periodStart", "periodEnd", "name");


--
-- Name: CategoryRule_categoryId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "CategoryRule_categoryId_idx" ON "public"."CategoryRule" USING "btree" ("categoryId");


--
-- Name: CategoryRule_field_operator_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "CategoryRule_field_operator_idx" ON "public"."CategoryRule" USING "btree" ("field", "operator");


--
-- Name: CategoryRule_userId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "CategoryRule_userId_idx" ON "public"."CategoryRule" USING "btree" ("userId");


--
-- Name: Category_parentId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Category_parentId_idx" ON "public"."Category" USING "btree" ("parentId");


--
-- Name: Category_userId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Category_userId_idx" ON "public"."Category" USING "btree" ("userId");


--
-- Name: Category_userId_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Category_userId_type_idx" ON "public"."Category" USING "btree" ("userId", "type");


--
-- Name: CounterpartyAlias_counterpartyId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "CounterpartyAlias_counterpartyId_idx" ON "public"."CounterpartyAlias" USING "btree" ("counterpartyId");


--
-- Name: Counterparty_userId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Counterparty_userId_idx" ON "public"."Counterparty" USING "btree" ("userId");


--
-- Name: Counterparty_userId_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Counterparty_userId_name_idx" ON "public"."Counterparty" USING "btree" ("userId", "name");


--
-- Name: DailyBaselineAccount_baseline_presentationSnapshot_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailyBaselineAccount_baseline_presentationSnapshot_key" ON "public"."DailySnapshotBaselineAccount" USING "btree" ("baselineId", "presentationSnapshotId");


--
-- Name: DailyBaseline_user_timestamp_currency_version_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailyBaseline_user_timestamp_currency_version_key" ON "public"."DailySnapshotBaseline" USING "btree" ("userId", "timestamp", "currency", "calculationVersion");


--
-- Name: DailySnapshotBaselineAccount_accountId_baselineId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "DailySnapshotBaselineAccount_accountId_baselineId_idx" ON "public"."DailySnapshotBaselineAccount" USING "btree" ("accountId", "baselineId");


--
-- Name: DailySnapshotBaselineAccount_baselineId_primarySnapshotId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailySnapshotBaselineAccount_baselineId_primarySnapshotId_key" ON "public"."DailySnapshotBaselineAccount" USING "btree" ("baselineId", "primarySnapshotId");


--
-- Name: DailySnapshotBaseline_netWorthSnapshotId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailySnapshotBaseline_netWorthSnapshotId_key" ON "public"."DailySnapshotBaseline" USING "btree" ("netWorthSnapshotId");


--
-- Name: DailySnapshotBaseline_userId_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "DailySnapshotBaseline_userId_timestamp_idx" ON "public"."DailySnapshotBaseline" USING "btree" ("userId", "timestamp");


--
-- Name: ExchangeRate_fromCurrency_toCurrency_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ExchangeRate_fromCurrency_toCurrency_date_idx" ON "public"."ExchangeRate" USING "btree" ("fromCurrency", "toCurrency", "date");


--
-- Name: ExchangeRate_fromCurrency_toCurrency_date_source_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ExchangeRate_fromCurrency_toCurrency_date_source_key" ON "public"."ExchangeRate" USING "btree" ("fromCurrency", "toCurrency", "date", "source");


--
-- Name: ExchangeRate_source_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ExchangeRate_source_date_idx" ON "public"."ExchangeRate" USING "btree" ("source", "date");


--
-- Name: Holding_accountId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Holding_accountId_idx" ON "public"."Holding" USING "btree" ("accountId");


--
-- Name: Holding_accountId_listingId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "Holding_accountId_listingId_key" ON "public"."Holding" USING "btree" ("accountId", "listingId");


--
-- Name: Holding_assetId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Holding_assetId_idx" ON "public"."Holding" USING "btree" ("assetId");


--
-- Name: Holding_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Holding_listingId_idx" ON "public"."Holding" USING "btree" ("listingId");


--
-- Name: ImportBatch_accountId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportBatch_accountId_createdAt_idx" ON "public"."ImportBatch" USING "btree" ("accountId", "createdAt");


--
-- Name: ImportBatch_source_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportBatch_source_status_idx" ON "public"."ImportBatch" USING "btree" ("source", "status");


--
-- Name: ImportBatch_userId_accountId_checksum_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportBatch_userId_accountId_checksum_key" ON "public"."ImportBatch" USING "btree" ("userId", "accountId", "checksum");


--
-- Name: ImportBatch_userId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportBatch_userId_createdAt_idx" ON "public"."ImportBatch" USING "btree" ("userId", "createdAt");


--
-- Name: ImportLog_importBatchId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportLog_importBatchId_createdAt_idx" ON "public"."ImportLog" USING "btree" ("importBatchId", "createdAt");


--
-- Name: ImportLog_level_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportLog_level_createdAt_idx" ON "public"."ImportLog" USING "btree" ("level", "createdAt");


--
-- Name: ImportRow_deduplicationKey_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportRow_deduplicationKey_idx" ON "public"."ImportRow" USING "btree" ("deduplicationKey");


--
-- Name: ImportRow_importBatchId_rowNumber_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportRow_importBatchId_rowNumber_key" ON "public"."ImportRow" USING "btree" ("importBatchId", "rowNumber");


--
-- Name: ImportRow_importBatchId_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportRow_importBatchId_status_idx" ON "public"."ImportRow" USING "btree" ("importBatchId", "status");


--
-- Name: InvestmentEvent_accountId_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentEvent_accountId_date_idx" ON "public"."InvestmentEvent" USING "btree" ("accountId", "date");


--
-- Name: InvestmentEvent_accountId_externalId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentEvent_accountId_externalId_idx" ON "public"."InvestmentEvent" USING "btree" ("accountId", "externalId");


--
-- Name: InvestmentEvent_importBatchId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentEvent_importBatchId_idx" ON "public"."InvestmentEvent" USING "btree" ("importBatchId");


--
-- Name: InvestmentEvent_orderId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentEvent_orderId_idx" ON "public"."InvestmentEvent" USING "btree" ("orderId");


--
-- Name: InvestmentMovement_accountId_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovement_accountId_createdAt_idx" ON "public"."InvestmentMovement" USING "btree" ("accountId", "createdAt");


--
-- Name: InvestmentMovement_assetId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovement_assetId_idx" ON "public"."InvestmentMovement" USING "btree" ("assetId");


--
-- Name: InvestmentMovement_eventId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovement_eventId_idx" ON "public"."InvestmentMovement" USING "btree" ("eventId");


--
-- Name: InvestmentMovement_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovement_kind_idx" ON "public"."InvestmentMovement" USING "btree" ("kind");


--
-- Name: InvestmentMovement_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovement_listingId_idx" ON "public"."InvestmentMovement" USING "btree" ("listingId");


--
-- Name: LiabilityBalance_accountId_effectiveAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiabilityBalance_accountId_effectiveAt_idx" ON "public"."LiabilityBalance" USING "btree" ("accountId", "effectiveAt");


--
-- Name: LiabilityBalance_accountId_effectiveAt_source_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiabilityBalance_accountId_effectiveAt_source_key" ON "public"."LiabilityBalance" USING "btree" ("accountId", "effectiveAt", "source");


--
-- Name: LiabilityBalance_accountId_source_externalId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiabilityBalance_accountId_source_externalId_key" ON "public"."LiabilityBalance" USING "btree" ("accountId", "source", "externalId");


--
-- Name: NetWorthSnapshot_source_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "NetWorthSnapshot_source_timestamp_idx" ON "public"."NetWorthSnapshot" USING "btree" ("source", "timestamp");


--
-- Name: NetWorthSnapshot_userId_granularity_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "NetWorthSnapshot_userId_granularity_timestamp_idx" ON "public"."NetWorthSnapshot" USING "btree" ("userId", "granularity", "timestamp");


--
-- Name: NetWorthSnapshot_userId_timestamp_currency_granularity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "NetWorthSnapshot_userId_timestamp_currency_granularity_key" ON "public"."NetWorthSnapshot" USING "btree" ("userId", "timestamp", "currency", "granularity");


--
-- Name: PriceSnapshot_assetId_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PriceSnapshot_assetId_timestamp_idx" ON "public"."PriceSnapshot" USING "btree" ("assetId", "timestamp");


--
-- Name: PriceSnapshot_listingId_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PriceSnapshot_listingId_timestamp_idx" ON "public"."PriceSnapshot" USING "btree" ("listingId", "timestamp");


--
-- Name: PriceSnapshot_listingId_timestamp_source_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "PriceSnapshot_listingId_timestamp_source_key" ON "public"."PriceSnapshot" USING "btree" ("listingId", "timestamp", "source");


--
-- Name: PriceSnapshot_source_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PriceSnapshot_source_timestamp_idx" ON "public"."PriceSnapshot" USING "btree" ("source", "timestamp");


--
-- Name: TransactionPair_fromTransactionId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "TransactionPair_fromTransactionId_key" ON "public"."TransactionPair" USING "btree" ("fromTransactionId");


--
-- Name: TransactionPair_toTransactionId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "TransactionPair_toTransactionId_key" ON "public"."TransactionPair" USING "btree" ("toTransactionId");


--
-- Name: TransactionSplit_categoryId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "TransactionSplit_categoryId_idx" ON "public"."TransactionSplit" USING "btree" ("categoryId");


--
-- Name: TransactionSplit_transactionId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "TransactionSplit_transactionId_idx" ON "public"."TransactionSplit" USING "btree" ("transactionId");


--
-- Name: Transaction_accountId_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Transaction_accountId_date_idx" ON "public"."Transaction" USING "btree" ("accountId", "date");


--
-- Name: Transaction_accountId_externalId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Transaction_accountId_externalId_idx" ON "public"."Transaction" USING "btree" ("accountId", "externalId");


--
-- Name: Transaction_categoryId_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Transaction_categoryId_date_idx" ON "public"."Transaction" USING "btree" ("categoryId", "date");


--
-- Name: Transaction_importBatchId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "Transaction_importBatchId_idx" ON "public"."Transaction" USING "btree" ("importBatchId");


--
-- Name: User_email_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "User_email_key" ON "public"."User" USING "btree" ("email");


--
-- Name: Account Account_initializeCanonicalState; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "Account_initializeCanonicalState" AFTER INSERT ON "public"."Account" FOR EACH ROW EXECUTE FUNCTION "public"."initializeAccountCanonicalState"();


--
-- Name: AccountCanonicalChange AccountCanonicalChange_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountCanonicalChange"
    ADD CONSTRAINT "AccountCanonicalChange_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountCanonicalState AccountCanonicalState_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountCanonicalState"
    ADD CONSTRAINT "AccountCanonicalState_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountInvite AccountInvite_acceptedById_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountInvite"
    ADD CONSTRAINT "AccountInvite_acceptedById_fkey" FOREIGN KEY ("acceptedById") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: AccountInvite AccountInvite_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountInvite"
    ADD CONSTRAINT "AccountInvite_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountInvite AccountInvite_inviterId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountInvite"
    ADD CONSTRAINT "AccountInvite_inviterId_fkey" FOREIGN KEY ("inviterId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: AccountMember AccountMember_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountMember"
    ADD CONSTRAINT "AccountMember_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountMember AccountMember_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountMember"
    ADD CONSTRAINT "AccountMember_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountSnapshotCanonicalBoundary AccountSnapshotBoundary_liabilityBalanceId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotCanonicalBoundary"
    ADD CONSTRAINT "AccountSnapshotBoundary_liabilityBalanceId_fkey" FOREIGN KEY ("selectedLiabilityBalanceId") REFERENCES "public"."LiabilityBalance"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: AccountSnapshotCanonicalBoundary AccountSnapshotCanonicalBoundary_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotCanonicalBoundary"
    ADD CONSTRAINT "AccountSnapshotCanonicalBoundary_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountSnapshotCanonicalBoundary AccountSnapshotCanonicalBoundary_snapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotCanonicalBoundary"
    ADD CONSTRAINT "AccountSnapshotCanonicalBoundary_snapshotId_fkey" FOREIGN KEY ("snapshotId") REFERENCES "public"."AccountSnapshot"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountSnapshotItem AccountSnapshotItem_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotItem"
    ADD CONSTRAINT "AccountSnapshotItem_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: AccountSnapshotItem AccountSnapshotItem_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotItem"
    ADD CONSTRAINT "AccountSnapshotItem_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: AccountSnapshotItem AccountSnapshotItem_snapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshotItem"
    ADD CONSTRAINT "AccountSnapshotItem_snapshotId_fkey" FOREIGN KEY ("snapshotId") REFERENCES "public"."AccountSnapshot"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AccountSnapshot AccountSnapshot_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshot"
    ADD CONSTRAINT "AccountSnapshot_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AssetAlias AssetAlias_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetAlias"
    ADD CONSTRAINT "AssetAlias_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AssetListing AssetListing_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetListing"
    ADD CONSTRAINT "AssetListing_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BackgroundJob BackgroundJob_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BackgroundJob"
    ADD CONSTRAINT "BackgroundJob_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BackgroundJob BackgroundJob_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BackgroundJob"
    ADD CONSTRAINT "BackgroundJob_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetAccount BudgetAccount_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAccount"
    ADD CONSTRAINT "BudgetAccount_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetAccount BudgetAccount_budgetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAccount"
    ADD CONSTRAINT "BudgetAccount_budgetId_fkey" FOREIGN KEY ("budgetId") REFERENCES "public"."Budget"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetAlert BudgetAlert_budgetItemId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAlert"
    ADD CONSTRAINT "BudgetAlert_budgetItemId_fkey" FOREIGN KEY ("budgetItemId") REFERENCES "public"."BudgetItem"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetAlert BudgetAlert_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetAlert"
    ADD CONSTRAINT "BudgetAlert_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: BudgetItemCategory BudgetItemCategory_budgetItemId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetItemCategory"
    ADD CONSTRAINT "BudgetItemCategory_budgetItemId_fkey" FOREIGN KEY ("budgetItemId") REFERENCES "public"."BudgetItem"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetItemCategory BudgetItemCategory_categoryId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetItemCategory"
    ADD CONSTRAINT "BudgetItemCategory_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "public"."Category"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: BudgetItem BudgetItem_budgetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."BudgetItem"
    ADD CONSTRAINT "BudgetItem_budgetId_fkey" FOREIGN KEY ("budgetId") REFERENCES "public"."Budget"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Budget Budget_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Budget"
    ADD CONSTRAINT "Budget_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: CategoryRule CategoryRule_categoryId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."CategoryRule"
    ADD CONSTRAINT "CategoryRule_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "public"."Category"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Category Category_parentId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Category"
    ADD CONSTRAINT "Category_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES "public"."Category"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: CounterpartyAlias CounterpartyAlias_counterpartyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."CounterpartyAlias"
    ADD CONSTRAINT "CounterpartyAlias_counterpartyId_fkey" FOREIGN KEY ("counterpartyId") REFERENCES "public"."Counterparty"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Counterparty Counterparty_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Counterparty"
    ADD CONSTRAINT "Counterparty_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_baselineId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_baselineId_fkey" FOREIGN KEY ("baselineId") REFERENCES "public"."DailySnapshotBaseline"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_presentationSnapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_presentationSnapshotId_fkey" FOREIGN KEY ("presentationSnapshotId") REFERENCES "public"."AccountSnapshot"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_primarySnapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_primarySnapshotId_fkey" FOREIGN KEY ("primarySnapshotId") REFERENCES "public"."AccountSnapshot"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaselineAccount DailySnapshotBaselineAccount_selectedLiabilityBalanceId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailySnapshotBaselineAccount_selectedLiabilityBalanceId_fkey" FOREIGN KEY ("selectedLiabilityBalanceId") REFERENCES "public"."LiabilityBalance"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_netWorthSnapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_netWorthSnapshotId_fkey" FOREIGN KEY ("netWorthSnapshotId") REFERENCES "public"."NetWorthSnapshot"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Holding Holding_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Holding"
    ADD CONSTRAINT "Holding_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: Holding Holding_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Holding"
    ADD CONSTRAINT "Holding_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: Holding Holding_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Holding"
    ADD CONSTRAINT "Holding_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportBatch ImportBatch_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportBatch"
    ADD CONSTRAINT "ImportBatch_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ImportBatch ImportBatch_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportBatch"
    ADD CONSTRAINT "ImportBatch_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ImportLog ImportLog_importBatchId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportLog"
    ADD CONSTRAINT "ImportLog_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "public"."ImportBatch"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ImportRow ImportRow_importBatchId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportRow"
    ADD CONSTRAINT "ImportRow_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "public"."ImportBatch"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: InvestmentEvent InvestmentEvent_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentEvent"
    ADD CONSTRAINT "InvestmentEvent_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentEvent InvestmentEvent_importBatchId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentEvent"
    ADD CONSTRAINT "InvestmentEvent_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "public"."ImportBatch"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: InvestmentMovement InvestmentMovement_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovement"
    ADD CONSTRAINT "InvestmentMovement_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentMovement InvestmentMovement_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovement"
    ADD CONSTRAINT "InvestmentMovement_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: InvestmentMovement InvestmentMovement_eventId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovement"
    ADD CONSTRAINT "InvestmentMovement_eventId_fkey" FOREIGN KEY ("eventId") REFERENCES "public"."InvestmentEvent"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: InvestmentMovement InvestmentMovement_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovement"
    ADD CONSTRAINT "InvestmentMovement_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiabilityBalance LiabilityBalance_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."LiabilityBalance"
    ADD CONSTRAINT "LiabilityBalance_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: NetWorthSnapshot NetWorthSnapshot_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PriceSnapshot PriceSnapshot_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PriceSnapshot"
    ADD CONSTRAINT "PriceSnapshot_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PriceSnapshot PriceSnapshot_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PriceSnapshot"
    ADD CONSTRAINT "PriceSnapshot_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TransactionPair TransactionPair_fromTransactionId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionPair"
    ADD CONSTRAINT "TransactionPair_fromTransactionId_fkey" FOREIGN KEY ("fromTransactionId") REFERENCES "public"."Transaction"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: TransactionPair TransactionPair_toTransactionId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionPair"
    ADD CONSTRAINT "TransactionPair_toTransactionId_fkey" FOREIGN KEY ("toTransactionId") REFERENCES "public"."Transaction"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: TransactionSplit TransactionSplit_categoryId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionSplit"
    ADD CONSTRAINT "TransactionSplit_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "public"."Category"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: TransactionSplit TransactionSplit_transactionId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionSplit"
    ADD CONSTRAINT "TransactionSplit_transactionId_fkey" FOREIGN KEY ("transactionId") REFERENCES "public"."Transaction"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Transaction Transaction_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Transaction"
    ADD CONSTRAINT "Transaction_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: Transaction Transaction_categoryId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Transaction"
    ADD CONSTRAINT "Transaction_categoryId_fkey" FOREIGN KEY ("categoryId") REFERENCES "public"."Category"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: Transaction Transaction_importBatchId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."Transaction"
    ADD CONSTRAINT "Transaction_importBatchId_fkey" FOREIGN KEY ("importBatchId") REFERENCES "public"."ImportBatch"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--
