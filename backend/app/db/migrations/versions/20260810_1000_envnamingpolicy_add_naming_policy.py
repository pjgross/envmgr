"""B2: the environment naming policy, and the stored name verdict

Revision ID: envnamingpolicy
Revises: contention
Create Date: 2026-08-10

Additive: one table, one nullable column, and NO BACKFILL AT ALL.

No tenant has a policy at migration time, so `environment.name_compliant` is
correctly NULL for every existing row — the column's null-means-no-pattern-
applies semantics are what make the backfill unnecessary rather than merely
deferred. Rows get their verdict from `recompute_tenant` the moment a policy is
first saved.
"""
import sqlalchemy as sa
from alembic import op

revision = "envnamingpolicy"
down_revision = "contention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_naming_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenant.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("name_pattern", sa.String(length=500), nullable=True),
        sa.Column("name_pattern_example", sa.String(length=200), nullable=True),
        sa.Column(
            "required_attributes", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "grace_days", sa.Integer(), nullable=False, server_default=sa.text("14")
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # Base's timestamps. Six tables shipped without these once and the
        # migration-built database was broken for months — see the hardening
        # programme.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_environment_naming_policy_tenant_id",
        "environment_naming_policy",
        ["tenant_id"],
    )
    op.add_column(
        "environment", sa.Column("name_compliant", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("environment", "name_compliant")
    op.drop_index(
        "ix_environment_naming_policy_tenant_id",
        table_name="environment_naming_policy",
    )
    op.drop_table("environment_naming_policy")
