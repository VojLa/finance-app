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
-- Name: SnapshotSeriesJobKind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE "public"."SnapshotSeriesJobKind" AS ENUM (
    'rebuild',
    'capture'
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
-- Name: guard_snapshot_series_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION "public"."guard_snapshot_series_immutable"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'snapshot series publication metadata is immutable';
        END $$;


--
-- Name: guard_snapshot_series_point_link(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION "public"."guard_snapshot_series_point_link"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD."validToVersion" IS NULL
                AND NEW."validToVersion" IS NOT NULL
                AND (to_jsonb(NEW) - 'validToVersion') = (to_jsonb(OLD) - 'validToVersion') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'snapshot series point links may only close once';
        END $$;


--
-- Name: guard_snapshot_series_version_state(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION "public"."guard_snapshot_series_version_state"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW."lastVersion" < OLD."lastVersion" THEN
                RAISE EXCEPTION 'snapshot series version cannot decrease';
            END IF;
            IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RAISE EXCEPTION 'snapshot series version state survives retirement';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END $$;


--
-- Name: initializeAccountCanonicalState(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION "public"."initializeAccountCanonicalState"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
            BEGIN
                INSERT INTO "public"."AccountCanonicalState"
                    ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
                VALUES (
                    NEW."id",
                    0,
                    0,
                    CASE WHEN NEW."type" IN ('broker', 'exchange', 'crypto_wallet') THEN 0 ELSE NULL END,
                    NEW."updatedAt"
                );
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
    "notes" "text",
    "creditLimit" numeric(18,6),
    CONSTRAINT "Account_credit_limit_only_for_credit_cards" CHECK ((("creditLimit" IS NULL) OR (("type" = 'credit_card'::"public"."AccountType") AND ("creditLimit" > (0)::numeric))))
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
    "investmentCostBasis" numeric(18,6),
    "liabilitiesValue" numeric(18,6) NOT NULL,
    "totalValue" numeric(18,6) NOT NULL,
    "isRecalculated" boolean DEFAULT false NOT NULL,
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "calculationVersion" integer DEFAULT 1 NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "netDepositsValue" numeric(18,6),
    "realizedPnlValue" numeric(18,6),
    "unrealizedPnlValue" numeric(18,6),
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
    "exchangeRates" "jsonb",
    "generationId" "text" NOT NULL,
    "liabilitiesValueByCurrency" "jsonb"
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
    "nativeCostBasisByCurrency" "jsonb",
    "averageBuyPrice" numeric(28,10),
    "averageBuyPriceCurrency" "text",
    CONSTRAINT "AccountSnapshotItem_cost_basis_completeness" CHECK (((("costBasis" IS NULL) = ("costCurrency" IS NULL)) AND (("costBasis" IS NULL) = ("nativeCostBasis" IS NULL)) AND (("costBasis" IS NULL) = ("nativeCostCurrency" IS NULL)) AND (("costBasis" IS NULL) = ("nativeCostBasisByCurrency" IS NULL)) AND (("costBasis" IS NULL) = ("averageBuyPrice" IS NULL)) AND (("costBasis" IS NULL) = ("averageBuyPriceCurrency" IS NULL)))),
    CONSTRAINT "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object" CHECK ((("nativeCostBasisByCurrency" IS NULL) OR (("jsonb_typeof"("nativeCostBasisByCurrency") = 'object'::"text") AND ("nativeCostBasisByCurrency" <> '{}'::"jsonb"))))
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
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "listingId" "text"
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
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "basePriority" integer DEFAULT 0 NOT NULL,
    CONSTRAINT "AssetListing_basePriority_nonnegative" CHECK (("basePriority" >= 0))
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
    "backgroundJobId" "text",
    "generationId" "text" NOT NULL,
    CONSTRAINT "DailySnapshotBaseline_calculationVersion_positive" CHECK (("calculationVersion" > 0)),
    CONSTRAINT "DailySnapshotBaseline_day_or_import_anchor" CHECK (((("granularity" = 'day'::"public"."SnapshotGranularity") AND ("backgroundJobId" IS NULL)) OR (("granularity" = 'minute'::"public"."SnapshotGranularity") AND ((("source" = 'import_event'::"public"."SnapshotSource") AND ("backgroundJobId" IS NOT NULL)) OR (("source" = ANY (ARRAY['manual_recalculation'::"public"."SnapshotSource", 'price_refresh'::"public"."SnapshotSource", 'scheduled'::"public"."SnapshotSource", 'holdings_recalculation'::"public"."SnapshotSource"])) AND ("backgroundJobId" IS NULL))))))
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
    "generationId" "text" NOT NULL,
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
    "avgBuyPrice" numeric(28,10),
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
    "costBasisByCurrency" "jsonb",
    CONSTRAINT "Holding_costBasisByCurrency_nonempty_object" CHECK ((("costBasisByCurrency" IS NULL) OR (("jsonb_typeof"("costBasisByCurrency") = 'object'::"text") AND ("costBasisByCurrency" <> '{}'::"jsonb")))),
    CONSTRAINT "Holding_cost_basis_completeness_pair" CHECK ((("avgBuyPrice" IS NULL) = ("costBasisByCurrency" IS NULL)))
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
-- Name: ImportJobAffectedAccount; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportJobAffectedAccount" (
    "jobId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ImportJobBatch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportJobBatch" (
    "jobId" "text" NOT NULL,
    "batchId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ImportJobPublicationTarget; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportJobPublicationTarget" (
    "jobId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "bucket" timestamp(3) without time zone NOT NULL,
    "publishedAt" timestamp(3) without time zone,
    CONSTRAINT "ImportJobPublicationTarget_bucket_minute_aligned" CHECK (("date_trunc"('minute'::"text", "bucket") = "bucket"))
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
-- Name: ImportSourceOccurrence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."ImportSourceOccurrence" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "source" "public"."ImportSource" NOT NULL,
    "fingerprintHash" "text" NOT NULL,
    "ordinal" integer NOT NULL,
    "representativeImportRowId" "text" NOT NULL,
    "representativeImportBatchId" "text" NOT NULL,
    "canonicalTransactionId" "text",
    "version" integer DEFAULT 1 NOT NULL,
    "flags" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "ImportSourceOccurrence_fingerprintHash_sha256" CHECK (("fingerprintHash" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "ImportSourceOccurrence_flags_bounded" CHECK (("octet_length"(("flags")::"text") <= 16384)),
    CONSTRAINT "ImportSourceOccurrence_flags_object" CHECK (("jsonb_typeof"("flags") = 'object'::"text")),
    CONSTRAINT "ImportSourceOccurrence_ordinal_positive" CHECK (("ordinal" >= 1)),
    CONSTRAINT "ImportSourceOccurrence_version_positive" CHECK (("version" >= 1))
);


--
-- Name: InvestmentAccountSnapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."InvestmentAccountSnapshot" (
    "id" "text" NOT NULL,
    "accountSnapshotId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "valuationTimestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "source" "public"."SnapshotSource" NOT NULL,
    "currency" "text" NOT NULL,
    "cashValue" numeric(18,6) NOT NULL,
    "investmentValue" numeric(18,6) NOT NULL,
    "investmentCostBasis" numeric(18,6),
    "netDepositsValue" numeric(18,6),
    "realizedPnlValue" numeric(18,6),
    "unrealizedPnlValue" numeric(18,6),
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
    "priceEvidence" "jsonb",
    "exchangeRates" "jsonb",
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "calculationVersion" integer DEFAULT 1 NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: InvestmentAccountSnapshotItem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."InvestmentAccountSnapshotItem" (
    "id" "text" NOT NULL,
    "investmentAccountSnapshotId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "assetId" "text",
    "listingId" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "pricePerUnit" numeric(28,10) NOT NULL,
    "priceCurrency" "text",
    "priceSource" "public"."PriceSource",
    "priceTimestamp" timestamp(3) without time zone,
    "value" numeric(18,6) NOT NULL,
    "costBasis" numeric(18,6),
    "allocationPct" numeric(8,4) NOT NULL,
    "nativeValue" numeric(28,10),
    "valueCurrency" "text",
    "nativeCostBasis" numeric(28,10),
    "nativeCostCurrency" "text",
    "priceEvidence" "jsonb",
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
-- Name: InvestmentMovementValuationEvidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."InvestmentMovementValuationEvidence" (
    "id" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "movementId" "text" NOT NULL,
    "revision" integer NOT NULL,
    "canonicalRevision" bigint NOT NULL,
    "effectiveAt" timestamp(3) without time zone NOT NULL,
    "calculationVersion" integer NOT NULL,
    "selectionInterval" "text" NOT NULL,
    "inputFingerprint" "text" NOT NULL,
    "priceSnapshotId" "text" NOT NULL,
    "exchangeRateId" "text",
    "priceAmount" numeric(28,10) NOT NULL,
    "priceCurrency" "text" NOT NULL,
    "priceSource" "public"."PriceSource" NOT NULL,
    "priceTimestamp" timestamp(3) without time zone NOT NULL,
    "fxRate" numeric(18,8),
    "fxFromCurrency" "text",
    "fxToCurrency" "text",
    "fxSource" "public"."ExchangeRateSource",
    "fxTimestamp" timestamp(3) without time zone,
    "pricePerUnit" numeric(28,10) NOT NULL,
    "valueAmount" numeric(28,10) NOT NULL,
    "valueCurrency" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "InvestmentMovementValuationEvidence_calculationVersion_positive" CHECK (("calculationVersion" >= 1)),
    CONSTRAINT "InvestmentMovementValuationEvidence_canonicalRevision_positive" CHECK (("canonicalRevision" >= 1)),
    CONSTRAINT "InvestmentMovementValuationEvidence_fx_complete_or_absent" CHECK (((("exchangeRateId" IS NULL) AND ("fxRate" IS NULL) AND ("fxFromCurrency" IS NULL) AND ("fxToCurrency" IS NULL) AND ("fxSource" IS NULL) AND ("fxTimestamp" IS NULL)) OR (("exchangeRateId" IS NOT NULL) AND ("fxRate" IS NOT NULL) AND ("fxFromCurrency" IS NOT NULL) AND ("fxToCurrency" IS NOT NULL) AND ("fxSource" IS NOT NULL) AND ("fxTimestamp" IS NOT NULL)))),
    CONSTRAINT "InvestmentMovementValuationEvidence_priceAmount_positive" CHECK (("priceAmount" > (0)::numeric)),
    CONSTRAINT "InvestmentMovementValuationEvidence_pricePerUnit_positive" CHECK (("pricePerUnit" > (0)::numeric)),
    CONSTRAINT "InvestmentMovementValuationEvidence_revision_positive" CHECK (("revision" >= 1)),
    CONSTRAINT "InvestmentMovementValuationEvidence_selectionInterval_known" CHECK (("selectionInterval" = ANY (ARRAY['30min'::"text", '1day'::"text"]))),
    CONSTRAINT "InvestmentMovementValuationEvidence_valueAmount_positive" CHECK (("valueAmount" > (0)::numeric))
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
    "exchangeRates" "jsonb",
    "generationId" "text" NOT NULL
);


--
-- Name: PortfolioSnapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."PortfolioSnapshot" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "valuationTimestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "source" "public"."SnapshotSource" NOT NULL,
    "currency" "text" NOT NULL,
    "cashValue" numeric(18,6) NOT NULL,
    "investmentValue" numeric(18,6) NOT NULL,
    "investmentCostBasis" numeric(18,6),
    "netDepositsValue" numeric(18,6),
    "realizedPnlValue" numeric(18,6),
    "unrealizedPnlValue" numeric(18,6),
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
    "priceEvidence" "jsonb",
    "exchangeRates" "jsonb",
    "calculatedAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "calculationVersion" integer DEFAULT 1 NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: PortfolioSnapshotInput; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."PortfolioSnapshotInput" (
    "portfolioSnapshotId" "text" NOT NULL,
    "investmentAccountSnapshotId" "text" NOT NULL,
    "accountSnapshotId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: PortfolioSnapshotItem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."PortfolioSnapshotItem" (
    "id" "text" NOT NULL,
    "portfolioSnapshotId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "assetId" "text",
    "listingId" "text" NOT NULL,
    "symbol" "text" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "pricePerUnit" numeric(28,10) NOT NULL,
    "priceCurrency" "text",
    "priceSource" "public"."PriceSource",
    "priceTimestamp" timestamp(3) without time zone,
    "value" numeric(18,6) NOT NULL,
    "costBasis" numeric(18,6),
    "allocationPct" numeric(8,4) NOT NULL,
    "nativeValue" numeric(28,10),
    "valueCurrency" "text",
    "nativeCostBasis" numeric(28,10),
    "nativeCostCurrency" "text",
    "priceEvidence" "jsonb",
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: PortfolioSnapshotItemAccount; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."PortfolioSnapshotItemAccount" (
    "portfolioSnapshotItemId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "portfolioSnapshotId" "text" NOT NULL,
    "investmentAccountSnapshotId" "text" NOT NULL,
    "accountSnapshotId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "listingId" "text" NOT NULL,
    "quantity" numeric(28,10) NOT NULL,
    "value" numeric(18,6) NOT NULL,
    "costBasis" numeric(18,6),
    "allocationPct" numeric(8,4) NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
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
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "providerSymbol" "text"
);


--
-- Name: SnapshotGeneration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotGeneration" (
    "id" "text" NOT NULL,
    "state" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    "publishedAt" timestamp(3) without time zone,
    CONSTRAINT "SnapshotGeneration_publication_lifecycle" CHECK (((("state" = 'staged'::"text") AND ("publishedAt" IS NULL)) OR (("state" = 'published'::"text") AND ("publishedAt" IS NOT NULL)))),
    CONSTRAINT "SnapshotGeneration_state_known" CHECK (("state" = ANY (ARRAY['staged'::"text", 'published'::"text"])))
);


--
-- Name: SnapshotGenerationTarget; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotGenerationTarget" (
    "generationId" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    "stagedByJobId" "text",
    "stagedLeaseVersion" bigint,
    "stagedLeaseOwner" "text",
    CONSTRAINT "SnapshotGenerationTarget_staging_provenance_complete" CHECK (((("stagedByJobId" IS NULL) AND ("stagedLeaseVersion" IS NULL) AND ("stagedLeaseOwner" IS NULL)) OR (("stagedByJobId" IS NOT NULL) AND ("stagedLeaseVersion" IS NOT NULL) AND ("stagedLeaseVersion" >= 0) AND ("stagedLeaseOwner" IS NOT NULL))))
);


--
-- Name: SnapshotSeriesCanonicalInvalidation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesCanonicalInvalidation" (
    "userId" "text" NOT NULL,
    "accountId" "text" NOT NULL,
    "canonicalRevision" bigint NOT NULL,
    "kind" "text" NOT NULL,
    "entityId" "text" NOT NULL,
    "financialTimestamp" timestamp(3) without time zone NOT NULL,
    "firstDirtyEpoch" bigint NOT NULL,
    "invalidatedAt" timestamp(3) without time zone NOT NULL,
    "resolvedAt" timestamp(3) without time zone,
    "resolvedSnapshotGenerationId" "text",
    CONSTRAINT "SnapshotSeriesCanonicalInvalidation_firstDirtyEpoch_positive" CHECK (("firstDirtyEpoch" >= 1))
);


--
-- Name: SnapshotSeriesDirtyState; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesDirtyState" (
    "userId" "text" NOT NULL,
    "dirtyFrom" timestamp(3) without time zone NOT NULL,
    "dirtyEpoch" bigint NOT NULL,
    "scopeDirty" boolean DEFAULT false NOT NULL,
    "reasonMask" integer NOT NULL,
    "requestedAt" timestamp(3) without time zone NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesDirtyState_valid" CHECK ((("dirtyEpoch" >= 1) AND ("reasonMask" >= 1)))
);


--
-- Name: SnapshotSeriesHead; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesHead" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "version" bigint NOT NULL,
    "parentHeadId" "text",
    "generationId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesHead_parent_distinct" CHECK ((("parentHeadId" IS NULL) OR ("parentHeadId" <> "id"))),
    CONSTRAINT "SnapshotSeriesHead_version_positive" CHECK (("version" >= 1))
);


--
-- Name: SnapshotSeriesPointLink; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesPointLink" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "timestamp" timestamp(3) without time zone NOT NULL,
    "granularity" "public"."SnapshotGranularity" NOT NULL,
    "validFromVersion" bigint NOT NULL,
    "validToVersion" bigint,
    "generationId" "text" NOT NULL,
    "baselineId" "text" NOT NULL,
    "portfolioSnapshotId" "text" NOT NULL,
    "netWorthSnapshotId" "text" NOT NULL,
    "createdAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesPointLink_from_positive" CHECK (("validFromVersion" >= 1)),
    CONSTRAINT "SnapshotSeriesPointLink_to_after_from" CHECK ((("validToVersion" IS NULL) OR ("validToVersion" > "validFromVersion")))
);


--
-- Name: SnapshotSeriesPublicationReceipt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesPublicationReceipt" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "jobId" "text" NOT NULL,
    "generationId" "text" NOT NULL,
    "headId" "text" NOT NULL,
    "committedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesPublicationReceipt_job_id_bounded" CHECK ((("char_length"("jobId") >= 1) AND ("char_length"("jobId") <= 200)))
);


--
-- Name: SnapshotSeriesRebuildJob; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesRebuildJob" (
    "id" "text" NOT NULL,
    "userId" "text" NOT NULL,
    "requestedByBackgroundJobId" "text",
    "kind" "public"."SnapshotSeriesJobKind" NOT NULL,
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
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesRebuildJob_attempts_valid" CHECK ((("attemptCount" >= 0) AND ("attemptCount" <= "maxAttempts") AND (("maxAttempts" >= 1) AND ("maxAttempts" <= 20)))),
    CONSTRAINT "SnapshotSeriesRebuildJob_checkpoint_object" CHECK (("jsonb_typeof"("checkpoint") = 'object'::"text")),
    CONSTRAINT "SnapshotSeriesRebuildJob_completed_has_result" CHECK ((("status" = 'completed'::"public"."BackgroundJobStatus") = ("result" IS NOT NULL))),
    CONSTRAINT "SnapshotSeriesRebuildJob_error_pair_complete" CHECK (((("errorCode" IS NULL) AND ("errorMessage" IS NULL)) OR (("errorCode" IS NOT NULL) AND ("errorMessage" IS NOT NULL)))),
    CONSTRAINT "SnapshotSeriesRebuildJob_idempotencyKey_bounded" CHECK ((("char_length"("idempotencyKey") >= 1) AND ("char_length"("idempotencyKey") <= 200))),
    CONSTRAINT "SnapshotSeriesRebuildJob_leaseVersion_nonnegative" CHECK (("leaseVersion" >= 0)),
    CONSTRAINT "SnapshotSeriesRebuildJob_lease_complete_or_absent" CHECK (((("leaseOwner" IS NULL) AND ("leaseExpiresAt" IS NULL) AND ("leaseHeartbeatAt" IS NULL)) OR (("leaseOwner" IS NOT NULL) AND ("leaseExpiresAt" IS NOT NULL) AND ("leaseHeartbeatAt" IS NOT NULL)))),
    CONSTRAINT "SnapshotSeriesRebuildJob_payload_object" CHECK ((("jsonb_typeof"("payload") = 'object'::"text") AND ("payload" <> '{}'::"jsonb"))),
    CONSTRAINT "SnapshotSeriesRebuildJob_progress_object" CHECK (("jsonb_typeof"("progress") = 'object'::"text")),
    CONSTRAINT "SnapshotSeriesRebuildJob_result_object" CHECK ((("result" IS NULL) OR ("jsonb_typeof"("result") = 'object'::"text"))),
    CONSTRAINT "SnapshotSeriesRebuildJob_running_has_lease" CHECK ((("status" = 'running'::"public"."BackgroundJobStatus") = ("leaseOwner" IS NOT NULL))),
    CONSTRAINT "SnapshotSeriesRebuildJob_terminal_has_finishedAt" CHECK ((("status" = ANY (ARRAY['completed'::"public"."BackgroundJobStatus", 'failed'::"public"."BackgroundJobStatus"])) = ("finishedAt" IS NOT NULL)))
);


--
-- Name: SnapshotSeriesScheduleState; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesScheduleState" (
    "userId" "text" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "timezone" "text" DEFAULT 'Europe/Prague'::"text" NOT NULL,
    "cadenceMinutes" smallint DEFAULT 30 NOT NULL,
    "nextCaptureAt" timestamp(3) without time zone NOT NULL,
    "lastCapturedBucket" timestamp(3) without time zone,
    "lastDirtyEpoch" bigint DEFAULT 0 NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesScheduleState_capture_policy" CHECK ((("timezone" = 'Europe/Prague'::"text") AND ("cadenceMinutes" = 30))),
    CONSTRAINT "SnapshotSeriesScheduleState_lastDirtyEpoch_nonnegative" CHECK (("lastDirtyEpoch" >= 0)),
    CONSTRAINT "SnapshotSeriesScheduleState_nextCapture_minute_aligned" CHECK (("date_trunc"('minute'::"text", "nextCaptureAt") = "nextCaptureAt"))
);


--
-- Name: SnapshotSeriesVersionState; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."SnapshotSeriesVersionState" (
    "userId" "text" NOT NULL,
    "lastVersion" bigint DEFAULT 0 NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "SnapshotSeriesVersionState_lastVersion_nonnegative" CHECK (("lastVersion" >= 0))
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
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "classification" "public"."TransactionClassification",
    "source" "public"."ImportSource",
    "evidenceVersion" integer,
    "evidenceHash" "text",
    "backgroundJobId" "text",
    "publishedAt" timestamp(3) without time zone,
    CONSTRAINT "TransactionPair_background_job_requires_evidence" CHECK ((("backgroundJobId" IS NULL) OR ("classification" IS NOT NULL))),
    CONSTRAINT "TransactionPair_publication_requires_background_job" CHECK ((("publishedAt" IS NULL) OR ("backgroundJobId" IS NOT NULL))),
    CONSTRAINT "TransactionPair_reconciliation_evidence_complete_or_legacy" CHECK (((("classification" IS NULL) AND ("source" IS NULL) AND ("evidenceVersion" IS NULL) AND ("evidenceHash" IS NULL)) OR (("classification" IS NOT NULL) AND ("source" IS NOT NULL) AND ("evidenceVersion" >= 1) AND ("evidenceHash" ~ '^[0-9a-f]{64}$'::"text"))))
);


--
-- Name: TransactionReportingEvidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."TransactionReportingEvidence" (
    "transactionId" "text" NOT NULL,
    "sourceAmount" numeric(18,6) NOT NULL,
    "sourceCurrency" "text" NOT NULL,
    "sourceEventTime" timestamp(3) without time zone NOT NULL,
    "reportingAmount" numeric(18,6) NOT NULL,
    "reportingCurrency" "text" NOT NULL,
    "exchangeRateId" "text" NOT NULL,
    "calculationVersion" integer NOT NULL,
    "backgroundJobId" "text",
    "publishedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "TransactionReportingEvidence_calculationVersion_positive" CHECK (("calculationVersion" >= 1)),
    CONSTRAINT "TransactionReportingEvidence_direct_conversion" CHECK (("sourceCurrency" <> "reportingCurrency")),
    CONSTRAINT "TransactionReportingEvidence_publish_requires_job" CHECK ((("publishedAt" IS NULL) OR ("backgroundJobId" IS NOT NULL))),
    CONSTRAINT "TransactionReportingEvidence_reportingAmount_nonzero" CHECK (("reportingAmount" <> (0)::numeric)),
    CONSTRAINT "TransactionReportingEvidence_reportingCurrency_iso4217" CHECK (("reportingCurrency" ~ '^[A-Z]{3}$'::"text")),
    CONSTRAINT "TransactionReportingEvidence_sourceAmount_nonzero" CHECK (("sourceAmount" <> (0)::numeric)),
    CONSTRAINT "TransactionReportingEvidence_sourceCurrency_iso4217" CHECK (("sourceCurrency" ~ '^[A-Z]{3}$'::"text"))
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
-- Name: UserReadModelPublication; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."UserReadModelPublication" (
    "userId" "text" NOT NULL,
    "version" "text" NOT NULL,
    "baselineId" "text" NOT NULL,
    "scopes" "jsonb" NOT NULL,
    "publishedAt" timestamp(3) without time zone NOT NULL,
    "generationId" "text" NOT NULL,
    "generationState" "text" DEFAULT 'published'::"text" NOT NULL,
    "seriesHeadId" "text" NOT NULL,
    CONSTRAINT "UserReadModelPublication_generation_published" CHECK (("generationState" = 'published'::"text")),
    CONSTRAINT "UserReadModelPublication_version_nonempty" CHECK (("version" <> ''::"text"))
);


--
-- Name: UserReadModelPublicationWatermark; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE "public"."UserReadModelPublicationWatermark" (
    "userId" "text" NOT NULL,
    "causalAt" timestamp(3) without time zone NOT NULL,
    "kind" "text" NOT NULL,
    "generationId" "text",
    "updatedAt" timestamp(3) without time zone NOT NULL,
    CONSTRAINT "UserReadModelPublicationWatermark_generation_matches_kind" CHECK (((("kind" = 'published'::"text") AND ("generationId" IS NOT NULL)) OR (("kind" = 'retired'::"text") AND ("generationId" IS NULL)))),
    CONSTRAINT "UserReadModelPublicationWatermark_kind_known" CHECK (("kind" = ANY (ARRAY['published'::"text", 'retired'::"text"])))
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
-- Name: AccountSnapshot AccountSnapshot_id_generation_account_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshot"
    ADD CONSTRAINT "AccountSnapshot_id_generation_account_key" UNIQUE ("id", "generationId", "accountId");


--
-- Name: AccountSnapshot AccountSnapshot_id_generation_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshot"
    ADD CONSTRAINT "AccountSnapshot_id_generation_key" UNIQUE ("id", "generationId");


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
-- Name: DailySnapshotBaseline DailySnapshotBaseline_id_generation_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_id_generation_key" UNIQUE ("id", "generationId");


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_id_generation_user_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_id_generation_user_key" UNIQUE ("id", "generationId", "userId");


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
-- Name: ImportJobAffectedAccount ImportJobAffectedAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobAffectedAccount"
    ADD CONSTRAINT "ImportJobAffectedAccount_pkey" PRIMARY KEY ("jobId", "accountId");


--
-- Name: ImportJobBatch ImportJobBatch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobBatch"
    ADD CONSTRAINT "ImportJobBatch_pkey" PRIMARY KEY ("jobId", "batchId");


--
-- Name: ImportJobPublicationTarget ImportJobPublicationTarget_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobPublicationTarget"
    ADD CONSTRAINT "ImportJobPublicationTarget_pkey" PRIMARY KEY ("jobId", "userId");


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
-- Name: ImportSourceOccurrence ImportSourceOccurrence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportSourceOccurrence"
    ADD CONSTRAINT "ImportSourceOccurrence_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentAccountSnapshotItem InvestmentAccountSnapshotItem_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshotItem"
    ADD CONSTRAINT "InvestmentAccountSnapshotItem_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentAccountSnapshotItem InvestmentAccountSnapshotItem_snapshot_listing_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshotItem"
    ADD CONSTRAINT "InvestmentAccountSnapshotItem_snapshot_listing_key" UNIQUE ("investmentAccountSnapshotId", "listingId");


--
-- Name: InvestmentAccountSnapshot InvestmentAccountSnapshot_accountSnapshot_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshot"
    ADD CONSTRAINT "InvestmentAccountSnapshot_accountSnapshot_key" UNIQUE ("accountSnapshotId");


--
-- Name: InvestmentAccountSnapshot InvestmentAccountSnapshot_id_generation_account_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshot"
    ADD CONSTRAINT "InvestmentAccountSnapshot_id_generation_account_key" UNIQUE ("id", "generationId", "accountId");


--
-- Name: InvestmentAccountSnapshot InvestmentAccountSnapshot_input_coordinate_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshot"
    ADD CONSTRAINT "InvestmentAccountSnapshot_input_coordinate_key" UNIQUE ("id", "accountSnapshotId", "generationId", "accountId");


--
-- Name: InvestmentAccountSnapshot InvestmentAccountSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshot"
    ADD CONSTRAINT "InvestmentAccountSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentEvent InvestmentEvent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentEvent"
    ADD CONSTRAINT "InvestmentEvent_pkey" PRIMARY KEY ("id");


--
-- Name: InvestmentMovementValuationEvidence InvestmentMovementValuationEvidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovementValuationEvidence"
    ADD CONSTRAINT "InvestmentMovementValuationEvidence_pkey" PRIMARY KEY ("id");


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
-- Name: NetWorthSnapshot NetWorthSnapshot_id_generation_user_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_id_generation_user_key" UNIQUE ("id", "generationId", "userId");


--
-- Name: NetWorthSnapshot NetWorthSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: PortfolioSnapshotInput PortfolioSnapshotInput_coordinate_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotInput"
    ADD CONSTRAINT "PortfolioSnapshotInput_coordinate_key" UNIQUE ("portfolioSnapshotId", "investmentAccountSnapshotId", "accountSnapshotId", "generationId", "userId", "accountId");


--
-- Name: PortfolioSnapshotInput PortfolioSnapshotInput_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotInput"
    ADD CONSTRAINT "PortfolioSnapshotInput_pkey" PRIMARY KEY ("portfolioSnapshotId", "investmentAccountSnapshotId");


--
-- Name: PortfolioSnapshotItemAccount PortfolioSnapshotItemAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItemAccount"
    ADD CONSTRAINT "PortfolioSnapshotItemAccount_pkey" PRIMARY KEY ("portfolioSnapshotItemId", "accountId");


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_identity_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_identity_key" UNIQUE ("id", "portfolioSnapshotId", "generationId", "userId", "listingId");


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_pkey" PRIMARY KEY ("id");


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_snapshot_listing_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_snapshot_listing_key" UNIQUE ("portfolioSnapshotId", "listingId");


--
-- Name: PortfolioSnapshot PortfolioSnapshot_coordinate_generation_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshot"
    ADD CONSTRAINT "PortfolioSnapshot_coordinate_generation_key" UNIQUE ("userId", "timestamp", "currency", "granularity", "generationId");


--
-- Name: PortfolioSnapshot PortfolioSnapshot_id_generation_user_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshot"
    ADD CONSTRAINT "PortfolioSnapshot_id_generation_user_key" UNIQUE ("id", "generationId", "userId");


--
-- Name: PortfolioSnapshot PortfolioSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshot"
    ADD CONSTRAINT "PortfolioSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: PriceSnapshot PriceSnapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PriceSnapshot"
    ADD CONSTRAINT "PriceSnapshot_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotGenerationTarget SnapshotGenerationTarget_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGenerationTarget"
    ADD CONSTRAINT "SnapshotGenerationTarget_pkey" PRIMARY KEY ("generationId", "userId");


--
-- Name: SnapshotGeneration SnapshotGeneration_id_state_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGeneration"
    ADD CONSTRAINT "SnapshotGeneration_id_state_key" UNIQUE ("id", "state");


--
-- Name: SnapshotGeneration SnapshotGeneration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGeneration"
    ADD CONSTRAINT "SnapshotGeneration_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotSeriesCanonicalInvalidation SnapshotSeriesCanonicalInvalidation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesCanonicalInvalidation"
    ADD CONSTRAINT "SnapshotSeriesCanonicalInvalidation_pkey" PRIMARY KEY ("userId", "accountId", "canonicalRevision");


--
-- Name: SnapshotSeriesDirtyState SnapshotSeriesDirtyState_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesDirtyState"
    ADD CONSTRAINT "SnapshotSeriesDirtyState_pkey" PRIMARY KEY ("userId");


--
-- Name: SnapshotSeriesHead SnapshotSeriesHead_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesHead"
    ADD CONSTRAINT "SnapshotSeriesHead_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_no_overlap" EXCLUDE USING "gist" ("userId" WITH =, "timestamp" WITH =, "granularity" WITH =, "int8range"("validFromVersion", "validToVersion", '[)'::"text") WITH &&);


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotSeriesPublicationReceipt SnapshotSeriesPublicationReceipt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPublicationReceipt"
    ADD CONSTRAINT "SnapshotSeriesPublicationReceipt_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotSeriesRebuildJob SnapshotSeriesRebuildJob_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesRebuildJob"
    ADD CONSTRAINT "SnapshotSeriesRebuildJob_pkey" PRIMARY KEY ("id");


--
-- Name: SnapshotSeriesScheduleState SnapshotSeriesScheduleState_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesScheduleState"
    ADD CONSTRAINT "SnapshotSeriesScheduleState_pkey" PRIMARY KEY ("userId");


--
-- Name: SnapshotSeriesVersionState SnapshotSeriesVersionState_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesVersionState"
    ADD CONSTRAINT "SnapshotSeriesVersionState_pkey" PRIMARY KEY ("userId");


--
-- Name: TransactionPair TransactionPair_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionPair"
    ADD CONSTRAINT "TransactionPair_pkey" PRIMARY KEY ("id");


--
-- Name: TransactionReportingEvidence TransactionReportingEvidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionReportingEvidence"
    ADD CONSTRAINT "TransactionReportingEvidence_pkey" PRIMARY KEY ("transactionId");


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
-- Name: UserReadModelPublicationWatermark UserReadModelPublicationWatermark_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublicationWatermark"
    ADD CONSTRAINT "UserReadModelPublicationWatermark_pkey" PRIMARY KEY ("userId");


--
-- Name: UserReadModelPublication UserReadModelPublication_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_pkey" PRIMARY KEY ("userId");


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
-- Name: AccountCanonicalChange_exact_identity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountCanonicalChange_exact_identity_key" ON "public"."AccountCanonicalChange" USING "btree" ("accountId", "revision", "kind", "entityId", "financialTimestamp");


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
-- Name: AccountSnapshot_coordinate_generation_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AccountSnapshot_coordinate_generation_key" ON "public"."AccountSnapshot" USING "btree" ("accountId", "timestamp", "currency", "granularity", "generationId");


--
-- Name: AccountSnapshot_generation_coordinate_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AccountSnapshot_generation_coordinate_idx" ON "public"."AccountSnapshot" USING "btree" ("generationId", "accountId", "granularity", "timestamp");


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
-- Name: AssetAlias_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "AssetAlias_listingId_idx" ON "public"."AssetAlias" USING "btree" ("listingId");


--
-- Name: AssetAlias_listingId_provider_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetAlias_listingId_provider_key" ON "public"."AssetAlias" USING "btree" ("listingId", "provider");


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
-- Name: AssetListing_id_assetId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "AssetListing_id_assetId_key" ON "public"."AssetListing" USING "btree" ("id", "assetId");


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
-- Name: BackgroundJob_id_userId_accountId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_id_userId_accountId_key" ON "public"."BackgroundJob" USING "btree" ("id", "userId", "accountId");


--
-- Name: BackgroundJob_id_userId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_id_userId_key" ON "public"."BackgroundJob" USING "btree" ("id", "userId");


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
-- Name: DailyBaseline_user_timestamp_currency_generation_version_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailyBaseline_user_timestamp_currency_generation_version_key" ON "public"."DailySnapshotBaseline" USING "btree" ("userId", "timestamp", "currency", "calculationVersion", "generationId");


--
-- Name: DailySnapshotBaselineAccount_accountId_baselineId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "DailySnapshotBaselineAccount_accountId_baselineId_idx" ON "public"."DailySnapshotBaselineAccount" USING "btree" ("accountId", "baselineId");


--
-- Name: DailySnapshotBaselineAccount_baselineId_primarySnapshotId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailySnapshotBaselineAccount_baselineId_primarySnapshotId_key" ON "public"."DailySnapshotBaselineAccount" USING "btree" ("baselineId", "primarySnapshotId");


--
-- Name: DailySnapshotBaseline_backgroundJob_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailySnapshotBaseline_backgroundJob_user_key" ON "public"."DailySnapshotBaseline" USING "btree" ("backgroundJobId", "userId");


--
-- Name: DailySnapshotBaseline_exact_point_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "DailySnapshotBaseline_exact_point_key" ON "public"."DailySnapshotBaseline" USING "btree" ("id", "generationId", "userId", "netWorthSnapshotId");


--
-- Name: DailySnapshotBaseline_generationId_userId_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "DailySnapshotBaseline_generationId_userId_timestamp_idx" ON "public"."DailySnapshotBaseline" USING "btree" ("generationId", "userId", "timestamp");


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
-- Name: ExchangeRate_id_fromCurrency_toCurrency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ExchangeRate_id_fromCurrency_toCurrency_key" ON "public"."ExchangeRate" USING "btree" ("id", "fromCurrency", "toCurrency");


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
-- Name: ImportBatch_id_accountId_source_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportBatch_id_accountId_source_key" ON "public"."ImportBatch" USING "btree" ("id", "accountId", "source");


--
-- Name: ImportBatch_id_userId_accountId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportBatch_id_userId_accountId_key" ON "public"."ImportBatch" USING "btree" ("id", "userId", "accountId");


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
-- Name: ImportJobAffectedAccount_accountId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportJobAffectedAccount_accountId_idx" ON "public"."ImportJobAffectedAccount" USING "btree" ("accountId");


--
-- Name: ImportJobBatch_batchId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportJobBatch_batchId_idx" ON "public"."ImportJobBatch" USING "btree" ("batchId");


--
-- Name: ImportJobPublicationTarget_unpublished_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportJobPublicationTarget_unpublished_idx" ON "public"."ImportJobPublicationTarget" USING "btree" ("userId", "bucket");


--
-- Name: ImportJobPublicationTarget_user_bucket_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportJobPublicationTarget_user_bucket_key" ON "public"."ImportJobPublicationTarget" USING "btree" ("userId", "bucket");


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
-- Name: ImportRow_id_importBatchId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportRow_id_importBatchId_key" ON "public"."ImportRow" USING "btree" ("id", "importBatchId");


--
-- Name: ImportRow_importBatchId_rowNumber_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportRow_importBatchId_rowNumber_key" ON "public"."ImportRow" USING "btree" ("importBatchId", "rowNumber");


--
-- Name: ImportRow_importBatchId_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportRow_importBatchId_status_idx" ON "public"."ImportRow" USING "btree" ("importBatchId", "status");


--
-- Name: ImportSourceOccurrence_accountId_source_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportSourceOccurrence_accountId_source_createdAt_idx" ON "public"."ImportSourceOccurrence" USING "btree" ("accountId", "source", "createdAt");


--
-- Name: ImportSourceOccurrence_canonicalTransactionId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "ImportSourceOccurrence_canonicalTransactionId_idx" ON "public"."ImportSourceOccurrence" USING "btree" ("canonicalTransactionId");


--
-- Name: ImportSourceOccurrence_fp_identity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportSourceOccurrence_fp_identity_key" ON "public"."ImportSourceOccurrence" USING "btree" ("accountId", "source", "fingerprintHash", "ordinal");


--
-- Name: ImportSourceOccurrence_rep_row_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "ImportSourceOccurrence_rep_row_key" ON "public"."ImportSourceOccurrence" USING "btree" ("representativeImportRowId");


--
-- Name: InvestmentAccountSnapshotItem_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentAccountSnapshotItem_listingId_idx" ON "public"."InvestmentAccountSnapshotItem" USING "btree" ("listingId");


--
-- Name: InvestmentAccountSnapshot_generation_account_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentAccountSnapshot_generation_account_timestamp_idx" ON "public"."InvestmentAccountSnapshot" USING "btree" ("generationId", "accountId", "timestamp");


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
-- Name: InvestmentMovementValuationEvidence_accountId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovementValuationEvidence_accountId_idx" ON "public"."InvestmentMovementValuationEvidence" USING "btree" ("accountId");


--
-- Name: InvestmentMovementValuationEvidence_movementId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "InvestmentMovementValuationEvidence_movementId_idx" ON "public"."InvestmentMovementValuationEvidence" USING "btree" ("movementId");


--
-- Name: InvestmentMovementValuationEvidence_movement_fingerprint_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "InvestmentMovementValuationEvidence_movement_fingerprint_key" ON "public"."InvestmentMovementValuationEvidence" USING "btree" ("movementId", "inputFingerprint");


--
-- Name: InvestmentMovementValuationEvidence_movement_revision_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "InvestmentMovementValuationEvidence_movement_revision_key" ON "public"."InvestmentMovementValuationEvidence" USING "btree" ("movementId", "revision");


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
-- Name: NetWorthSnapshot_coordinate_generation_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "NetWorthSnapshot_coordinate_generation_key" ON "public"."NetWorthSnapshot" USING "btree" ("userId", "timestamp", "currency", "granularity", "generationId");


--
-- Name: NetWorthSnapshot_generation_coordinate_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "NetWorthSnapshot_generation_coordinate_idx" ON "public"."NetWorthSnapshot" USING "btree" ("generationId", "userId", "granularity", "timestamp");


--
-- Name: NetWorthSnapshot_source_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "NetWorthSnapshot_source_timestamp_idx" ON "public"."NetWorthSnapshot" USING "btree" ("source", "timestamp");


--
-- Name: NetWorthSnapshot_userId_granularity_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "NetWorthSnapshot_userId_granularity_timestamp_idx" ON "public"."NetWorthSnapshot" USING "btree" ("userId", "granularity", "timestamp");


--
-- Name: PortfolioSnapshotItem_listingId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PortfolioSnapshotItem_listingId_idx" ON "public"."PortfolioSnapshotItem" USING "btree" ("listingId");


--
-- Name: PortfolioSnapshot_generation_user_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PortfolioSnapshot_generation_user_timestamp_idx" ON "public"."PortfolioSnapshot" USING "btree" ("generationId", "userId", "timestamp");


--
-- Name: PriceSnapshot_assetId_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "PriceSnapshot_assetId_timestamp_idx" ON "public"."PriceSnapshot" USING "btree" ("assetId", "timestamp");


--
-- Name: PriceSnapshot_id_listingId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "PriceSnapshot_id_listingId_key" ON "public"."PriceSnapshot" USING "btree" ("id", "listingId");


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
-- Name: SnapshotGenerationTarget_userId_generationId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotGenerationTarget_userId_generationId_idx" ON "public"."SnapshotGenerationTarget" USING "btree" ("userId", "generationId");


--
-- Name: SnapshotGeneration_state_createdAt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotGeneration_state_createdAt_idx" ON "public"."SnapshotGeneration" USING "btree" ("state", "createdAt");


--
-- Name: SnapshotSeriesCanonicalInvalidation_account_revision_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotSeriesCanonicalInvalidation_account_revision_idx" ON "public"."SnapshotSeriesCanonicalInvalidation" USING "btree" ("accountId", "canonicalRevision");


--
-- Name: SnapshotSeriesHead_id_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesHead_id_user_key" ON "public"."SnapshotSeriesHead" USING "btree" ("id", "userId");


--
-- Name: SnapshotSeriesHead_user_version_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesHead_user_version_key" ON "public"."SnapshotSeriesHead" USING "btree" ("userId", "version");


--
-- Name: SnapshotSeriesPointLink_coordinate_from_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesPointLink_coordinate_from_key" ON "public"."SnapshotSeriesPointLink" USING "btree" ("userId", "timestamp", "granularity", "validFromVersion");


--
-- Name: SnapshotSeriesPointLink_one_current_coordinate_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesPointLink_one_current_coordinate_key" ON "public"."SnapshotSeriesPointLink" USING "btree" ("userId", "timestamp", "granularity") WHERE ("validToVersion" IS NULL);


--
-- Name: SnapshotSeriesPointLink_user_visible_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotSeriesPointLink_user_visible_idx" ON "public"."SnapshotSeriesPointLink" USING "btree" ("userId", "granularity", "timestamp", "validFromVersion", "validToVersion");


--
-- Name: SnapshotSeriesPublicationReceipt_user_generation_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesPublicationReceipt_user_generation_key" ON "public"."SnapshotSeriesPublicationReceipt" USING "btree" ("userId", "generationId");


--
-- Name: SnapshotSeriesPublicationReceipt_user_head_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesPublicationReceipt_user_head_key" ON "public"."SnapshotSeriesPublicationReceipt" USING "btree" ("userId", "headId");


--
-- Name: SnapshotSeriesPublicationReceipt_user_job_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesPublicationReceipt_user_job_key" ON "public"."SnapshotSeriesPublicationReceipt" USING "btree" ("userId", "jobId");


--
-- Name: SnapshotSeriesRebuildJob_claim_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotSeriesRebuildJob_claim_idx" ON "public"."SnapshotSeriesRebuildJob" USING "btree" ("status", "runAfter", "leaseExpiresAt", "createdAt") WHERE ("status" = ANY (ARRAY['queued'::"public"."BackgroundJobStatus", 'retry_wait'::"public"."BackgroundJobStatus"]));


--
-- Name: SnapshotSeriesRebuildJob_id_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesRebuildJob_id_user_key" ON "public"."SnapshotSeriesRebuildJob" USING "btree" ("id", "userId");


--
-- Name: SnapshotSeriesRebuildJob_one_running_per_user_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesRebuildJob_one_running_per_user_key" ON "public"."SnapshotSeriesRebuildJob" USING "btree" ("userId") WHERE ("status" = 'running'::"public"."BackgroundJobStatus");


--
-- Name: SnapshotSeriesRebuildJob_user_kind_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "SnapshotSeriesRebuildJob_user_kind_idempotency_key" ON "public"."SnapshotSeriesRebuildJob" USING "btree" ("userId", "kind", "idempotencyKey");


--
-- Name: SnapshotSeriesScheduleState_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "SnapshotSeriesScheduleState_due_idx" ON "public"."SnapshotSeriesScheduleState" USING "btree" ("nextCaptureAt") WHERE "enabled";


--
-- Name: TransactionPair_backgroundJobId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "TransactionPair_backgroundJobId_idx" ON "public"."TransactionPair" USING "btree" ("backgroundJobId");


--
-- Name: TransactionPair_fromTransactionId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "TransactionPair_fromTransactionId_key" ON "public"."TransactionPair" USING "btree" ("fromTransactionId");


--
-- Name: TransactionPair_toTransactionId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "TransactionPair_toTransactionId_key" ON "public"."TransactionPair" USING "btree" ("toTransactionId");


--
-- Name: TransactionReportingEvidence_backgroundJobId_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "TransactionReportingEvidence_backgroundJobId_idx" ON "public"."TransactionReportingEvidence" USING "btree" ("backgroundJobId");


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
-- Name: Transaction_id_accountId_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "Transaction_id_accountId_key" ON "public"."Transaction" USING "btree" ("id", "accountId");


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
-- Name: SnapshotSeriesHead SnapshotSeriesHead_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "SnapshotSeriesHead_immutable" BEFORE DELETE OR UPDATE ON "public"."SnapshotSeriesHead" FOR EACH ROW EXECUTE FUNCTION "public"."guard_snapshot_series_immutable"();


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "SnapshotSeriesPointLink_guard" BEFORE DELETE OR UPDATE ON "public"."SnapshotSeriesPointLink" FOR EACH ROW EXECUTE FUNCTION "public"."guard_snapshot_series_point_link"();


--
-- Name: SnapshotSeriesPublicationReceipt SnapshotSeriesPublicationReceipt_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "SnapshotSeriesPublicationReceipt_immutable" BEFORE DELETE OR UPDATE ON "public"."SnapshotSeriesPublicationReceipt" FOR EACH ROW EXECUTE FUNCTION "public"."guard_snapshot_series_immutable"();


--
-- Name: SnapshotSeriesVersionState SnapshotSeriesVersionState_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER "SnapshotSeriesVersionState_guard" BEFORE DELETE OR UPDATE ON "public"."SnapshotSeriesVersionState" FOR EACH ROW EXECUTE FUNCTION "public"."guard_snapshot_series_version_state"();


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
-- Name: AccountSnapshot AccountSnapshot_generationId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AccountSnapshot"
    ADD CONSTRAINT "AccountSnapshot_generationId_fkey" FOREIGN KEY ("generationId") REFERENCES "public"."SnapshotGeneration"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: AssetAlias AssetAlias_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetAlias"
    ADD CONSTRAINT "AssetAlias_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AssetAlias AssetAlias_listing_asset_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."AssetAlias"
    ADD CONSTRAINT "AssetAlias_listing_asset_fkey" FOREIGN KEY ("listingId", "assetId") REFERENCES "public"."AssetListing"("id", "assetId") ON UPDATE CASCADE ON DELETE CASCADE;


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
-- Name: DailySnapshotBaselineAccount DailyBaselineAccount_baseline_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailyBaselineAccount_baseline_generation_fkey" FOREIGN KEY ("baselineId", "generationId") REFERENCES "public"."DailySnapshotBaseline"("id", "generationId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: DailySnapshotBaselineAccount DailyBaselineAccount_presentationSnapshot_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailyBaselineAccount_presentationSnapshot_generation_fkey" FOREIGN KEY ("presentationSnapshotId", "generationId", "accountId") REFERENCES "public"."AccountSnapshot"("id", "generationId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaselineAccount DailyBaselineAccount_primarySnapshot_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaselineAccount"
    ADD CONSTRAINT "DailyBaselineAccount_primarySnapshot_generation_fkey" FOREIGN KEY ("primarySnapshotId", "generationId", "accountId") REFERENCES "public"."AccountSnapshot"("id", "generationId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


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
-- Name: DailySnapshotBaseline DailySnapshotBaseline_backgroundJob_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_backgroundJob_user_fkey" FOREIGN KEY ("backgroundJobId", "userId") REFERENCES "public"."ImportJobPublicationTarget"("jobId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_generationId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_generationId_fkey" FOREIGN KEY ("generationId") REFERENCES "public"."SnapshotGeneration"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_generation_target_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_generation_target_fkey" FOREIGN KEY ("generationId", "userId") REFERENCES "public"."SnapshotGenerationTarget"("generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_netWorthSnapshotId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_netWorthSnapshotId_fkey" FOREIGN KEY ("netWorthSnapshotId") REFERENCES "public"."NetWorthSnapshot"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: DailySnapshotBaseline DailySnapshotBaseline_netWorthSnapshot_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."DailySnapshotBaseline"
    ADD CONSTRAINT "DailySnapshotBaseline_netWorthSnapshot_generation_fkey" FOREIGN KEY ("netWorthSnapshotId", "generationId", "userId") REFERENCES "public"."NetWorthSnapshot"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE CASCADE;


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
-- Name: ImportJobAffectedAccount ImportJobAffectedAccount_job_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobAffectedAccount"
    ADD CONSTRAINT "ImportJobAffectedAccount_job_user_fkey" FOREIGN KEY ("jobId", "userId") REFERENCES "public"."BackgroundJob"("id", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportJobAffectedAccount ImportJobAffectedAccount_member_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobAffectedAccount"
    ADD CONSTRAINT "ImportJobAffectedAccount_member_fkey" FOREIGN KEY ("accountId", "userId") REFERENCES "public"."AccountMember"("accountId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportJobBatch ImportJobBatch_batch_scope_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobBatch"
    ADD CONSTRAINT "ImportJobBatch_batch_scope_fkey" FOREIGN KEY ("batchId", "userId", "accountId") REFERENCES "public"."ImportBatch"("id", "userId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportJobBatch ImportJobBatch_job_scope_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobBatch"
    ADD CONSTRAINT "ImportJobBatch_job_scope_fkey" FOREIGN KEY ("jobId", "userId", "accountId") REFERENCES "public"."BackgroundJob"("id", "userId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportJobPublicationTarget ImportJobPublicationTarget_jobId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobPublicationTarget"
    ADD CONSTRAINT "ImportJobPublicationTarget_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "public"."BackgroundJob"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportJobPublicationTarget ImportJobPublicationTarget_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportJobPublicationTarget"
    ADD CONSTRAINT "ImportJobPublicationTarget_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


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
-- Name: ImportSourceOccurrence ImportSourceOccurrence_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportSourceOccurrence"
    ADD CONSTRAINT "ImportSourceOccurrence_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportSourceOccurrence ImportSourceOccurrence_rep_batch_scope_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportSourceOccurrence"
    ADD CONSTRAINT "ImportSourceOccurrence_rep_batch_scope_fkey" FOREIGN KEY ("representativeImportBatchId", "accountId", "source") REFERENCES "public"."ImportBatch"("id", "accountId", "source") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportSourceOccurrence ImportSourceOccurrence_rep_row_batch_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportSourceOccurrence"
    ADD CONSTRAINT "ImportSourceOccurrence_rep_row_batch_fkey" FOREIGN KEY ("representativeImportRowId", "representativeImportBatchId") REFERENCES "public"."ImportRow"("id", "importBatchId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ImportSourceOccurrence ImportSourceOccurrence_tx_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."ImportSourceOccurrence"
    ADD CONSTRAINT "ImportSourceOccurrence_tx_account_fkey" FOREIGN KEY ("canonicalTransactionId", "accountId") REFERENCES "public"."Transaction"("id", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentAccountSnapshotItem InvestmentAccountSnapshotItem_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshotItem"
    ADD CONSTRAINT "InvestmentAccountSnapshotItem_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: InvestmentAccountSnapshotItem InvestmentAccountSnapshotItem_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshotItem"
    ADD CONSTRAINT "InvestmentAccountSnapshotItem_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentAccountSnapshotItem InvestmentAccountSnapshotItem_snapshot_generation_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshotItem"
    ADD CONSTRAINT "InvestmentAccountSnapshotItem_snapshot_generation_account_fkey" FOREIGN KEY ("investmentAccountSnapshotId", "generationId", "accountId") REFERENCES "public"."InvestmentAccountSnapshot"("id", "generationId", "accountId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: InvestmentAccountSnapshot InvestmentAccountSnapshot_account_snapshot_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentAccountSnapshot"
    ADD CONSTRAINT "InvestmentAccountSnapshot_account_snapshot_generation_fkey" FOREIGN KEY ("accountSnapshotId", "generationId", "accountId") REFERENCES "public"."AccountSnapshot"("id", "generationId", "accountId") ON UPDATE CASCADE ON DELETE CASCADE;


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
-- Name: InvestmentMovementValuationEvidence InvestmentMovementValuationEvidence_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovementValuationEvidence"
    ADD CONSTRAINT "InvestmentMovementValuationEvidence_account_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentMovementValuationEvidence InvestmentMovementValuationEvidence_exchangeRate_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovementValuationEvidence"
    ADD CONSTRAINT "InvestmentMovementValuationEvidence_exchangeRate_fkey" FOREIGN KEY ("exchangeRateId") REFERENCES "public"."ExchangeRate"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentMovementValuationEvidence InvestmentMovementValuationEvidence_movement_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovementValuationEvidence"
    ADD CONSTRAINT "InvestmentMovementValuationEvidence_movement_fkey" FOREIGN KEY ("movementId") REFERENCES "public"."InvestmentMovement"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: InvestmentMovementValuationEvidence InvestmentMovementValuationEvidence_priceSnapshot_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."InvestmentMovementValuationEvidence"
    ADD CONSTRAINT "InvestmentMovementValuationEvidence_priceSnapshot_fkey" FOREIGN KEY ("priceSnapshotId") REFERENCES "public"."PriceSnapshot"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


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
-- Name: NetWorthSnapshot NetWorthSnapshot_generation_target_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_generation_target_fkey" FOREIGN KEY ("generationId", "userId") REFERENCES "public"."SnapshotGenerationTarget"("generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: NetWorthSnapshot NetWorthSnapshot_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."NetWorthSnapshot"
    ADD CONSTRAINT "NetWorthSnapshot_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PortfolioSnapshotInput PortfolioSnapshotInput_account_snapshot_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotInput"
    ADD CONSTRAINT "PortfolioSnapshotInput_account_snapshot_generation_fkey" FOREIGN KEY ("accountSnapshotId", "generationId", "accountId") REFERENCES "public"."AccountSnapshot"("id", "generationId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PortfolioSnapshotInput PortfolioSnapshotInput_investment_generation_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotInput"
    ADD CONSTRAINT "PortfolioSnapshotInput_investment_generation_account_fkey" FOREIGN KEY ("investmentAccountSnapshotId", "accountSnapshotId", "generationId", "accountId") REFERENCES "public"."InvestmentAccountSnapshot"("id", "accountSnapshotId", "generationId", "accountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PortfolioSnapshotInput PortfolioSnapshotInput_portfolio_generation_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotInput"
    ADD CONSTRAINT "PortfolioSnapshotInput_portfolio_generation_user_fkey" FOREIGN KEY ("portfolioSnapshotId", "generationId", "userId") REFERENCES "public"."PortfolioSnapshot"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PortfolioSnapshotItemAccount PortfolioSnapshotItemAccount_input_coordinate_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItemAccount"
    ADD CONSTRAINT "PortfolioSnapshotItemAccount_input_coordinate_fkey" FOREIGN KEY ("portfolioSnapshotId", "investmentAccountSnapshotId", "accountSnapshotId", "generationId", "userId", "accountId") REFERENCES "public"."PortfolioSnapshotInput"("portfolioSnapshotId", "investmentAccountSnapshotId", "accountSnapshotId", "generationId", "userId", "accountId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PortfolioSnapshotItemAccount PortfolioSnapshotItemAccount_item_coordinate_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItemAccount"
    ADD CONSTRAINT "PortfolioSnapshotItemAccount_item_coordinate_fkey" FOREIGN KEY ("portfolioSnapshotItemId", "portfolioSnapshotId", "generationId", "userId", "listingId") REFERENCES "public"."PortfolioSnapshotItem"("id", "portfolioSnapshotId", "generationId", "userId", "listingId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_assetId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "public"."Asset"("id") ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_listingId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "public"."AssetListing"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PortfolioSnapshotItem PortfolioSnapshotItem_snapshot_generation_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshotItem"
    ADD CONSTRAINT "PortfolioSnapshotItem_snapshot_generation_user_fkey" FOREIGN KEY ("portfolioSnapshotId", "generationId", "userId") REFERENCES "public"."PortfolioSnapshot"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PortfolioSnapshot PortfolioSnapshot_generation_target_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshot"
    ADD CONSTRAINT "PortfolioSnapshot_generation_target_fkey" FOREIGN KEY ("generationId", "userId") REFERENCES "public"."SnapshotGenerationTarget"("generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: PortfolioSnapshot PortfolioSnapshot_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."PortfolioSnapshot"
    ADD CONSTRAINT "PortfolioSnapshot_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


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
-- Name: SnapshotGenerationTarget SnapshotGenerationTarget_generationId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGenerationTarget"
    ADD CONSTRAINT "SnapshotGenerationTarget_generationId_fkey" FOREIGN KEY ("generationId") REFERENCES "public"."SnapshotGeneration"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotGenerationTarget SnapshotGenerationTarget_staging_job_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGenerationTarget"
    ADD CONSTRAINT "SnapshotGenerationTarget_staging_job_user_fkey" FOREIGN KEY ("stagedByJobId", "userId") REFERENCES "public"."SnapshotSeriesRebuildJob"("id", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotGenerationTarget SnapshotGenerationTarget_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotGenerationTarget"
    ADD CONSTRAINT "SnapshotGenerationTarget_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesCanonicalInvalidation SnapshotSeriesCanonicalInvalidation_accountId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesCanonicalInvalidation"
    ADD CONSTRAINT "SnapshotSeriesCanonicalInvalidation_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "public"."Account"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesCanonicalInvalidation SnapshotSeriesCanonicalInvalidation_canonical_change_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesCanonicalInvalidation"
    ADD CONSTRAINT "SnapshotSeriesCanonicalInvalidation_canonical_change_fkey" FOREIGN KEY ("accountId", "canonicalRevision", "kind", "entityId", "financialTimestamp") REFERENCES "public"."AccountCanonicalChange"("accountId", "revision", "kind", "entityId", "financialTimestamp") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesCanonicalInvalidation SnapshotSeriesCanonicalInvalidation_resolved_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesCanonicalInvalidation"
    ADD CONSTRAINT "SnapshotSeriesCanonicalInvalidation_resolved_generation_fkey" FOREIGN KEY ("resolvedSnapshotGenerationId") REFERENCES "public"."SnapshotGeneration"("id") ON UPDATE CASCADE ON DELETE SET NULL ("resolvedSnapshotGenerationId");


--
-- Name: SnapshotSeriesCanonicalInvalidation SnapshotSeriesCanonicalInvalidation_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesCanonicalInvalidation"
    ADD CONSTRAINT "SnapshotSeriesCanonicalInvalidation_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesDirtyState SnapshotSeriesDirtyState_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesDirtyState"
    ADD CONSTRAINT "SnapshotSeriesDirtyState_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesHead SnapshotSeriesHead_generation_target_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesHead"
    ADD CONSTRAINT "SnapshotSeriesHead_generation_target_fkey" FOREIGN KEY ("generationId", "userId") REFERENCES "public"."SnapshotGenerationTarget"("generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesHead SnapshotSeriesHead_parent_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesHead"
    ADD CONSTRAINT "SnapshotSeriesHead_parent_user_fkey" FOREIGN KEY ("parentHeadId", "userId") REFERENCES "public"."SnapshotSeriesHead"("id", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesHead SnapshotSeriesHead_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesHead"
    ADD CONSTRAINT "SnapshotSeriesHead_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_baseline_exact_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_baseline_exact_fkey" FOREIGN KEY ("baselineId", "generationId", "userId", "netWorthSnapshotId") REFERENCES "public"."DailySnapshotBaseline"("id", "generationId", "userId", "netWorthSnapshotId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_from_head_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_from_head_fkey" FOREIGN KEY ("userId", "validFromVersion") REFERENCES "public"."SnapshotSeriesHead"("userId", "version") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_net_worth_exact_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_net_worth_exact_fkey" FOREIGN KEY ("netWorthSnapshotId", "generationId", "userId") REFERENCES "public"."NetWorthSnapshot"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_portfolio_exact_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_portfolio_exact_fkey" FOREIGN KEY ("portfolioSnapshotId", "generationId", "userId") REFERENCES "public"."PortfolioSnapshot"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPointLink SnapshotSeriesPointLink_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPointLink"
    ADD CONSTRAINT "SnapshotSeriesPointLink_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesPublicationReceipt SnapshotSeriesPublicationReceipt_generation_target_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPublicationReceipt"
    ADD CONSTRAINT "SnapshotSeriesPublicationReceipt_generation_target_fkey" FOREIGN KEY ("generationId", "userId") REFERENCES "public"."SnapshotGenerationTarget"("generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPublicationReceipt SnapshotSeriesPublicationReceipt_head_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPublicationReceipt"
    ADD CONSTRAINT "SnapshotSeriesPublicationReceipt_head_user_fkey" FOREIGN KEY ("headId", "userId") REFERENCES "public"."SnapshotSeriesHead"("id", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SnapshotSeriesPublicationReceipt SnapshotSeriesPublicationReceipt_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesPublicationReceipt"
    ADD CONSTRAINT "SnapshotSeriesPublicationReceipt_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesRebuildJob SnapshotSeriesRebuildJob_requested_background_job_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesRebuildJob"
    ADD CONSTRAINT "SnapshotSeriesRebuildJob_requested_background_job_user_fkey" FOREIGN KEY ("requestedByBackgroundJobId", "userId") REFERENCES "public"."BackgroundJob"("id", "userId") ON UPDATE CASCADE ON DELETE SET NULL ("requestedByBackgroundJobId");


--
-- Name: SnapshotSeriesRebuildJob SnapshotSeriesRebuildJob_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesRebuildJob"
    ADD CONSTRAINT "SnapshotSeriesRebuildJob_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesScheduleState SnapshotSeriesScheduleState_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesScheduleState"
    ADD CONSTRAINT "SnapshotSeriesScheduleState_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SnapshotSeriesVersionState SnapshotSeriesVersionState_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."SnapshotSeriesVersionState"
    ADD CONSTRAINT "SnapshotSeriesVersionState_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TransactionPair TransactionPair_backgroundJobId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionPair"
    ADD CONSTRAINT "TransactionPair_backgroundJobId_fkey" FOREIGN KEY ("backgroundJobId") REFERENCES "public"."BackgroundJob"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


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
-- Name: TransactionReportingEvidence TransactionReportingEvidence_fx_direction_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionReportingEvidence"
    ADD CONSTRAINT "TransactionReportingEvidence_fx_direction_fkey" FOREIGN KEY ("exchangeRateId", "sourceCurrency", "reportingCurrency") REFERENCES "public"."ExchangeRate"("id", "fromCurrency", "toCurrency") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: TransactionReportingEvidence TransactionReportingEvidence_job_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionReportingEvidence"
    ADD CONSTRAINT "TransactionReportingEvidence_job_fkey" FOREIGN KEY ("backgroundJobId") REFERENCES "public"."BackgroundJob"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: TransactionReportingEvidence TransactionReportingEvidence_tx_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."TransactionReportingEvidence"
    ADD CONSTRAINT "TransactionReportingEvidence_tx_fkey" FOREIGN KEY ("transactionId") REFERENCES "public"."Transaction"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


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
-- Name: UserReadModelPublicationWatermark UserReadModelPublicationWatermark_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublicationWatermark"
    ADD CONSTRAINT "UserReadModelPublicationWatermark_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON DELETE CASCADE;


--
-- Name: UserReadModelPublication UserReadModelPublication_baselineId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_baselineId_fkey" FOREIGN KEY ("baselineId") REFERENCES "public"."DailySnapshotBaseline"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: UserReadModelPublication UserReadModelPublication_baseline_generation_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_baseline_generation_fkey" FOREIGN KEY ("baselineId", "generationId", "userId") REFERENCES "public"."DailySnapshotBaseline"("id", "generationId", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: UserReadModelPublication UserReadModelPublication_generationId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_generationId_fkey" FOREIGN KEY ("generationId") REFERENCES "public"."SnapshotGeneration"("id") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: UserReadModelPublication UserReadModelPublication_generation_published_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_generation_published_fkey" FOREIGN KEY ("generationId", "generationState") REFERENCES "public"."SnapshotGeneration"("id", "state") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: UserReadModelPublication UserReadModelPublication_series_head_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_series_head_user_fkey" FOREIGN KEY ("seriesHeadId", "userId") REFERENCES "public"."SnapshotSeriesHead"("id", "userId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: UserReadModelPublication UserReadModelPublication_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY "public"."UserReadModelPublication"
    ADD CONSTRAINT "UserReadModelPublication_userId_fkey" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
