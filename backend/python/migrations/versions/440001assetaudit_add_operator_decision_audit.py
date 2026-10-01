"""Append-only server-operator decisions for unresolved asset identity.

Revision ID: 440001assetaudit
Revises: 430001markethealth
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "440001assetaudit"
down_revision: str | None = "430001markethealth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_asset_alias_audit"
affected_tables = ("AssetAliasAudit",)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.create_table(
        "AssetAliasAudit",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("assetId", sa.Text(), nullable=False),
        sa.Column("listingId", sa.Text()),
        sa.Column("provider", sa.Text()),
        sa.Column("externalId", sa.Text()),
        sa.Column("beforeIdentity", postgresql.JSONB()),
        sa.Column("afterIdentity", postgresql.JSONB()),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3, timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="AssetAliasAudit_actor_nonblank"),
        sa.CheckConstraint(
            "action IN ('alias_created', 'alias_replayed', 'listing_created', 'listing_replayed', 'rejected')",
            name="AssetAliasAudit_action_allowed",
        ),
        schema="public",
    )
    op.create_index(
        "AssetAliasAudit_asset_created_idx",
        "AssetAliasAudit",
        ["assetId", "createdAt"],
        schema="public",
    )
    op.execute(
        'CREATE FUNCTION "public"."prevent_asset_alias_audit_mutation"() '
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'AssetAliasAudit is append-only'; END; $$"
    )
    op.execute(
        'CREATE TRIGGER "AssetAliasAudit_append_only" BEFORE UPDATE OR DELETE '
        'ON "public"."AssetAliasAudit" FOR EACH ROW '
        'EXECUTE FUNCTION "public"."prevent_asset_alias_audit_mutation"()'
    )


def downgrade() -> None:
    raise RuntimeError("Operator audit history must not be discarded by downgrade.")
