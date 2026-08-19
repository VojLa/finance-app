"""Add durable Raiffeisenbank reconciliation evidence foundations.

Revision ID: 3p0001rbfoundation
Revises: 3o0001unkbasis
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3p0001rbfoundation"
down_revision: str | None = "3o0001unkbasis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_import_reconciliation_evidence_foundation"
affected_tables = (
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
affected_columns = (
    "ImportBatch.id",
    "ImportBatch.userId",
    "ImportBatch.accountId",
    "ImportBatch.source",
    "ImportRow.id",
    "ImportRow.importBatchId",
    "Transaction.id",
    "Transaction.accountId",
    "ExchangeRate.id",
    "ExchangeRate.fromCurrency",
    "ExchangeRate.toCurrency",
    "BackgroundJob.id",
    "BackgroundJob.userId",
    "BackgroundJob.accountId",
    "ImportSourceOccurrence.id",
    "ImportSourceOccurrence.accountId",
    "ImportSourceOccurrence.source",
    "ImportSourceOccurrence.fingerprintHash",
    "ImportSourceOccurrence.ordinal",
    "ImportSourceOccurrence.representativeImportRowId",
    "ImportSourceOccurrence.representativeImportBatchId",
    "ImportSourceOccurrence.canonicalTransactionId",
    "ImportSourceOccurrence.version",
    "ImportSourceOccurrence.flags",
    "ImportSourceOccurrence.createdAt",
    "ImportSourceOccurrence.updatedAt",
    "TransactionReportingEvidence.transactionId",
    "TransactionReportingEvidence.sourceAmount",
    "TransactionReportingEvidence.sourceCurrency",
    "TransactionReportingEvidence.sourceEventTime",
    "TransactionReportingEvidence.reportingAmount",
    "TransactionReportingEvidence.reportingCurrency",
    "TransactionReportingEvidence.exchangeRateId",
    "TransactionReportingEvidence.calculationVersion",
    "TransactionReportingEvidence.backgroundJobId",
    "TransactionReportingEvidence.publishedAt",
    "TransactionReportingEvidence.createdAt",
    "ImportJobBatch.jobId",
    "ImportJobBatch.batchId",
    "ImportJobBatch.userId",
    "ImportJobBatch.accountId",
    "ImportJobBatch.createdAt",
    "ImportJobAffectedAccount.jobId",
    "ImportJobAffectedAccount.accountId",
    "ImportJobAffectedAccount.userId",
    "ImportJobAffectedAccount.createdAt",
    "TransactionPair.classification",
    "TransactionPair.source",
    "TransactionPair.evidenceVersion",
    "TransactionPair.evidenceHash",
    "TransactionPair.backgroundJobId",
    "TransactionPair.publishedAt",
)
prisma_schema_impact = "required"
data_migration = True

_IMPORT_SOURCE = postgresql.ENUM(
    name="ImportSource",
    schema="public",
    create_type=False,
)
_TRANSACTION_CLASSIFICATION = postgresql.ENUM(
    name="TransactionClassification",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    op.create_index(
        "ImportBatch_id_userId_accountId_key",
        "ImportBatch",
        ["id", "userId", "accountId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ImportBatch_id_accountId_source_key",
        "ImportBatch",
        ["id", "accountId", "source"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ImportRow_id_importBatchId_key",
        "ImportRow",
        ["id", "importBatchId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "Transaction_id_accountId_key",
        "Transaction",
        ["id", "accountId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ExchangeRate_id_fromCurrency_toCurrency_key",
        "ExchangeRate",
        ["id", "fromCurrency", "toCurrency"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "BackgroundJob_id_userId_accountId_key",
        "BackgroundJob",
        ["id", "userId", "accountId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "BackgroundJob_id_userId_key",
        "BackgroundJob",
        ["id", "userId"],
        unique=True,
        schema="public",
    )

    op.create_table(
        "ImportSourceOccurrence",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("source", _IMPORT_SOURCE, nullable=False),
        sa.Column("fingerprintHash", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("representativeImportRowId", sa.Text(), nullable=False),
        sa.Column("representativeImportBatchId", sa.Text(), nullable=False),
        sa.Column("canonicalTransactionId", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updatedAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            "\"fingerprintHash\" ~ '^[0-9a-f]{64}$'",
            name="ImportSourceOccurrence_fingerprintHash_sha256",
        ),
        sa.CheckConstraint('"ordinal" >= 1', name="ImportSourceOccurrence_ordinal_positive"),
        sa.CheckConstraint('"version" >= 1', name="ImportSourceOccurrence_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(\"flags\") = 'object'",
            name="ImportSourceOccurrence_flags_object",
        ),
        sa.CheckConstraint(
            'octet_length("flags"::text) <= 16384',
            name="ImportSourceOccurrence_flags_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="ImportSourceOccurrence_accountId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representativeImportRowId", "representativeImportBatchId"],
            ["public.ImportRow.id", "public.ImportRow.importBatchId"],
            name="ImportSourceOccurrence_rep_row_batch_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representativeImportBatchId", "accountId", "source"],
            ["public.ImportBatch.id", "public.ImportBatch.accountId", "public.ImportBatch.source"],
            name="ImportSourceOccurrence_rep_batch_scope_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonicalTransactionId", "accountId"],
            ["public.Transaction.id", "public.Transaction.accountId"],
            name="ImportSourceOccurrence_tx_account_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="ImportSourceOccurrence_pkey"),
        schema="public",
    )
    op.create_index(
        "ImportSourceOccurrence_fp_identity_key",
        "ImportSourceOccurrence",
        ["accountId", "source", "fingerprintHash", "ordinal"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ImportSourceOccurrence_rep_row_key",
        "ImportSourceOccurrence",
        ["representativeImportRowId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ImportSourceOccurrence_accountId_source_createdAt_idx",
        "ImportSourceOccurrence",
        ["accountId", "source", "createdAt"],
        schema="public",
    )
    op.create_index(
        "ImportSourceOccurrence_canonicalTransactionId_idx",
        "ImportSourceOccurrence",
        ["canonicalTransactionId"],
        schema="public",
    )

    op.create_table(
        "TransactionReportingEvidence",
        sa.Column("transactionId", sa.Text(), nullable=False),
        sa.Column("sourceAmount", sa.Numeric(18, 6), nullable=False),
        sa.Column("sourceCurrency", sa.Text(), nullable=False),
        sa.Column("sourceEventTime", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column("reportingAmount", sa.Numeric(18, 6), nullable=False),
        sa.Column("reportingCurrency", sa.Text(), nullable=False),
        sa.Column("exchangeRateId", sa.Text(), nullable=False),
        sa.Column("calculationVersion", sa.Integer(), nullable=False),
        sa.Column("backgroundJobId", sa.Text(), nullable=True),
        sa.Column("publishedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            '"sourceAmount" <> 0',
            name="TransactionReportingEvidence_sourceAmount_nonzero",
        ),
        sa.CheckConstraint(
            '"reportingAmount" <> 0',
            name="TransactionReportingEvidence_reportingAmount_nonzero",
        ),
        sa.CheckConstraint(
            "\"sourceCurrency\" ~ '^[A-Z]{3}$'",
            name="TransactionReportingEvidence_sourceCurrency_iso4217",
        ),
        sa.CheckConstraint(
            "\"reportingCurrency\" ~ '^[A-Z]{3}$'",
            name="TransactionReportingEvidence_reportingCurrency_iso4217",
        ),
        sa.CheckConstraint(
            '"sourceCurrency" <> "reportingCurrency"',
            name="TransactionReportingEvidence_direct_conversion",
        ),
        sa.CheckConstraint(
            '"calculationVersion" >= 1',
            name="TransactionReportingEvidence_calculationVersion_positive",
        ),
        sa.CheckConstraint(
            '"publishedAt" IS NULL OR "backgroundJobId" IS NOT NULL',
            name="TransactionReportingEvidence_publish_requires_job",
        ),
        sa.ForeignKeyConstraint(
            ["transactionId"],
            ["public.Transaction.id"],
            name="TransactionReportingEvidence_tx_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exchangeRateId", "sourceCurrency", "reportingCurrency"],
            [
                "public.ExchangeRate.id",
                "public.ExchangeRate.fromCurrency",
                "public.ExchangeRate.toCurrency",
            ],
            name="TransactionReportingEvidence_fx_direction_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["backgroundJobId"],
            ["public.BackgroundJob.id"],
            name="TransactionReportingEvidence_job_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transactionId", name="TransactionReportingEvidence_pkey"),
        schema="public",
    )
    op.create_index(
        "TransactionReportingEvidence_backgroundJobId_idx",
        "TransactionReportingEvidence",
        ["backgroundJobId"],
        schema="public",
    )

    op.create_table(
        "ImportJobBatch",
        sa.Column("jobId", sa.Text(), nullable=False),
        sa.Column("batchId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["jobId", "userId", "accountId"],
            [
                "public.BackgroundJob.id",
                "public.BackgroundJob.userId",
                "public.BackgroundJob.accountId",
            ],
            name="ImportJobBatch_job_scope_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batchId", "userId", "accountId"],
            [
                "public.ImportBatch.id",
                "public.ImportBatch.userId",
                "public.ImportBatch.accountId",
            ],
            name="ImportJobBatch_batch_scope_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("jobId", "batchId", name="ImportJobBatch_pkey"),
        schema="public",
    )
    op.create_index("ImportJobBatch_batchId_idx", "ImportJobBatch", ["batchId"], schema="public")

    op.create_table(
        "ImportJobAffectedAccount",
        sa.Column("jobId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["jobId", "userId"],
            ["public.BackgroundJob.id", "public.BackgroundJob.userId"],
            name="ImportJobAffectedAccount_job_user_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accountId", "userId"],
            ["public.AccountMember.accountId", "public.AccountMember.userId"],
            name="ImportJobAffectedAccount_member_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("jobId", "accountId", name="ImportJobAffectedAccount_pkey"),
        schema="public",
    )
    op.create_index(
        "ImportJobAffectedAccount_accountId_idx",
        "ImportJobAffectedAccount",
        ["accountId"],
        schema="public",
    )

    # 3l introduced durable import jobs before their relational manifest
    # existed.  A nonterminal legacy job must either receive the exact
    # immutable manifest that its canonical JSON payload proves, or stop this
    # upgrade: guessing a batch would let a worker publish another account's
    # history.  Completed legacy jobs deliberately stay unmanifested.  Their
    # pre-3p canonical rows have no reconstructible 3p pair/reporting
    # provenance, and the operational reader explicitly keeps unmanifested
    # rows legacy-visible instead of hiding them behind a newly invented job
    # boundary.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            r"""
            DO $$
            DECLARE
                job_record RECORD;
                payload_batch_ids TEXT[];
                sorted_batch_ids TEXT[];
                payload_count INTEGER;
                distinct_payload_count INTEGER;
                payload_strings_valid BOOLEAN;
                manifest_batch_count INTEGER;
                source_count INTEGER;
                initiator_member_exists BOOLEAN;
                validation_error TEXT;
            BEGIN
                FOR job_record IN
                    SELECT
                        "id",
                        "userId",
                        "accountId",
                        "status",
                        "payload",
                        "checkpoint",
                        "createdAt"
                    FROM "public"."BackgroundJob"
                    WHERE "kind" = 'import_workflow'::"public"."BackgroundJobKind"
                      AND "status" IN (
                          'queued'::"public"."BackgroundJobStatus",
                          'running'::"public"."BackgroundJobStatus",
                          'retry_wait'::"public"."BackgroundJobStatus",
                          'failed'::"public"."BackgroundJobStatus"
                      )
                    ORDER BY "id"
                LOOP
                    validation_error := NULL;
                    payload_batch_ids := NULL;
                    sorted_batch_ids := NULL;

                    IF (SELECT count(*) FROM jsonb_object_keys(job_record."payload")) <> 2
                       OR NOT (job_record."payload" ? 'schema_version')
                       OR NOT (job_record."payload" ? 'batch_ids')
                       OR job_record."payload" -> 'schema_version' <> '1'::jsonb
                       OR jsonb_typeof(job_record."payload" -> 'batch_ids') <> 'array'
                    THEN
                        validation_error := 'payload must be the exact canonical import schema';
                    ELSE
                        SELECT
                            count(*)::INTEGER,
                            count(DISTINCT value #>> '{}')::INTEGER,
                            bool_and(
                                jsonb_typeof(value) = 'string'
                                AND char_length(value #>> '{}') BETWEEN 1 AND 255
                                AND (value #>> '{}') = btrim(value #>> '{}', E' \t\n\r\f\v')
                            ),
                            array_agg(value #>> '{}'),
                            array_agg(
                                value #>> '{}'
                                ORDER BY (value #>> '{}') COLLATE "C"
                            )
                        INTO
                            payload_count,
                            distinct_payload_count,
                            payload_strings_valid,
                            payload_batch_ids,
                            sorted_batch_ids
                        FROM jsonb_array_elements(job_record."payload" -> 'batch_ids');

                        IF payload_count NOT BETWEEN 1 AND 10
                           OR distinct_payload_count <> payload_count
                           OR payload_strings_valid IS NOT TRUE
                           OR payload_batch_ids IS DISTINCT FROM sorted_batch_ids
                        THEN
                            validation_error := 'payload batch_ids are not canonical';
                        END IF;
                    END IF;

                    IF validation_error IS NULL THEN
                        SELECT
                            count(*)::INTEGER,
                            count(DISTINCT batch."source")::INTEGER
                        INTO manifest_batch_count, source_count
                        FROM "public"."ImportBatch" AS batch
                        WHERE batch."id" = ANY(payload_batch_ids)
                          AND batch."userId" = job_record."userId"
                          AND batch."accountId" = job_record."accountId";

                        IF manifest_batch_count <> payload_count OR source_count <> 1 THEN
                            validation_error := 'payload batches do not prove one scoped import source';
                        END IF;
                    END IF;

                    IF validation_error IS NULL THEN
                        SELECT EXISTS (
                            SELECT 1
                            FROM "public"."AccountMember" AS member
                            WHERE member."accountId" = job_record."accountId"
                              AND member."userId" = job_record."userId"
                        )
                        INTO initiator_member_exists;
                    END IF;

                    IF validation_error IS NOT NULL THEN
                        RAISE EXCEPTION
                            'Cannot backfill noncompleted import workflow job %: %',
                            job_record."id",
                            validation_error;
                    END IF;

                    INSERT INTO "public"."ImportJobBatch" (
                        "jobId", "batchId", "userId", "accountId", "createdAt"
                    )
                    SELECT
                        job_record."id",
                        batch_id,
                        job_record."userId",
                        job_record."accountId",
                        job_record."createdAt"
                    FROM unnest(payload_batch_ids) AS batch_id
                    ORDER BY batch_id COLLATE "C";

                    IF initiator_member_exists IS TRUE THEN
                        INSERT INTO "public"."ImportJobAffectedAccount" (
                            "jobId", "accountId", "userId", "createdAt"
                        )
                        VALUES (
                            job_record."id",
                            job_record."accountId",
                            job_record."userId",
                            job_record."createdAt"
                        );
                    END IF;

                    -- Legacy Raiffeisenbank jobs could already have passed
                    -- canonical posting before the 3p reconciliation/FX/
                    -- liability stages existed.  Restart them immediately
                    -- after posting so the new stages cannot be skipped.
                    IF source_count = 1
                       AND EXISTS (
                           SELECT 1
                           FROM "public"."ImportBatch" AS batch
                           WHERE batch."id" = payload_batch_ids[1]
                             AND batch."source" = 'raiffeisenbank'::"public"."ImportSource"
                       )
                       AND COALESCE(job_record."checkpoint" ->> 'phase', '')
                           IN ('rebuilding_holdings', 'refreshing_snapshot', 'completed')
                    THEN
                        UPDATE "public"."BackgroundJob"
                        SET
                            "checkpoint" = jsonb_build_object(
                                'schema_version', 1,
                                'phase', 'posting',
                                'completed_batch_ids', to_jsonb(payload_batch_ids)
                            ),
                            "progress" = jsonb_build_object(
                                'schema_version', 1,
                                'phase', 'posting',
                                'completed_units', payload_count * 5,
                                'total_units', (payload_count * 5) + 4,
                                'completed_batches', payload_count,
                                'total_batches', payload_count
                            )
                        WHERE "id" = job_record."id";
                    END IF;
                END LOOP;
            END $$;
            """
        )
    )

    op.add_column(
        "TransactionPair",
        sa.Column("classification", _TRANSACTION_CLASSIFICATION, nullable=True),
        schema="public",
    )
    op.add_column(
        "TransactionPair",
        sa.Column("source", _IMPORT_SOURCE, nullable=True),
        schema="public",
    )
    op.add_column(
        "TransactionPair",
        sa.Column("evidenceVersion", sa.Integer(), nullable=True),
        schema="public",
    )
    op.add_column(
        "TransactionPair",
        sa.Column("evidenceHash", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "TransactionPair",
        sa.Column("backgroundJobId", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "TransactionPair",
        sa.Column("publishedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "TransactionPair_backgroundJobId_fkey",
        "TransactionPair",
        "BackgroundJob",
        ["backgroundJobId"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "TransactionPair_reconciliation_evidence_complete_or_legacy",
        "TransactionPair",
        '(("classification" IS NULL AND "source" IS NULL '
        'AND "evidenceVersion" IS NULL AND "evidenceHash" IS NULL) OR '
        '("classification" IS NOT NULL AND "source" IS NOT NULL '
        'AND "evidenceVersion" >= 1 AND "evidenceHash" ~ \'^[0-9a-f]{64}$\'))',
        schema="public",
    )
    op.create_check_constraint(
        "TransactionPair_background_job_requires_evidence",
        "TransactionPair",
        '"backgroundJobId" IS NULL OR "classification" IS NOT NULL',
        schema="public",
    )
    op.create_check_constraint(
        "TransactionPair_publication_requires_background_job",
        "TransactionPair",
        '"publishedAt" IS NULL OR "backgroundJobId" IS NOT NULL',
        schema="public",
    )
    op.create_index(
        "TransactionPair_backgroundJobId_idx",
        "TransactionPair",
        ["backgroundJobId"],
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence_exists = connection.execute(
        sa.text(
            """
            SELECT
                EXISTS (SELECT 1 FROM "public"."ImportSourceOccurrence")
                OR EXISTS (SELECT 1 FROM "public"."TransactionReportingEvidence")
                OR EXISTS (SELECT 1 FROM "public"."ImportJobBatch")
                OR EXISTS (SELECT 1 FROM "public"."ImportJobAffectedAccount")
                OR EXISTS (
                    SELECT 1 FROM "public"."TransactionPair"
                    WHERE "classification" IS NOT NULL
                       OR "source" IS NOT NULL
                       OR "evidenceVersion" IS NOT NULL
                       OR "evidenceHash" IS NOT NULL
                       OR "backgroundJobId" IS NOT NULL
                       OR "publishedAt" IS NOT NULL
                )
            """
        )
    ).scalar_one()
    if evidence_exists:
        raise RuntimeError(
            "Cannot remove import reconciliation evidence while durable evidence exists."
        )

    op.drop_index("TransactionPair_backgroundJobId_idx", "TransactionPair", schema="public")
    op.drop_constraint(
        "TransactionPair_publication_requires_background_job",
        "TransactionPair",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "TransactionPair_background_job_requires_evidence",
        "TransactionPair",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "TransactionPair_reconciliation_evidence_complete_or_legacy",
        "TransactionPair",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "TransactionPair_backgroundJobId_fkey",
        "TransactionPair",
        schema="public",
        type_="foreignkey",
    )
    for column in (
        "publishedAt",
        "backgroundJobId",
        "evidenceHash",
        "evidenceVersion",
        "source",
        "classification",
    ):
        op.drop_column("TransactionPair", column, schema="public")

    op.drop_index(
        "ImportJobAffectedAccount_accountId_idx", "ImportJobAffectedAccount", schema="public"
    )
    op.drop_table("ImportJobAffectedAccount", schema="public")
    op.drop_index("ImportJobBatch_batchId_idx", "ImportJobBatch", schema="public")
    op.drop_table("ImportJobBatch", schema="public")
    op.drop_index(
        "TransactionReportingEvidence_backgroundJobId_idx",
        "TransactionReportingEvidence",
        schema="public",
    )
    op.drop_table("TransactionReportingEvidence", schema="public")
    op.drop_index(
        "ImportSourceOccurrence_canonicalTransactionId_idx",
        "ImportSourceOccurrence",
        schema="public",
    )
    op.drop_index(
        "ImportSourceOccurrence_rep_row_key",
        "ImportSourceOccurrence",
        schema="public",
    )
    op.drop_index(
        "ImportSourceOccurrence_fp_identity_key",
        "ImportSourceOccurrence",
        schema="public",
    )
    op.drop_index(
        "ImportSourceOccurrence_accountId_source_createdAt_idx",
        "ImportSourceOccurrence",
        schema="public",
    )
    op.drop_table("ImportSourceOccurrence", schema="public")

    for table, index in (
        ("BackgroundJob", "BackgroundJob_id_userId_key"),
        ("BackgroundJob", "BackgroundJob_id_userId_accountId_key"),
        ("ExchangeRate", "ExchangeRate_id_fromCurrency_toCurrency_key"),
        ("Transaction", "Transaction_id_accountId_key"),
        ("ImportRow", "ImportRow_id_importBatchId_key"),
        ("ImportBatch", "ImportBatch_id_accountId_source_key"),
        ("ImportBatch", "ImportBatch_id_userId_accountId_key"),
    ):
        op.drop_index(index, table, schema="public")
