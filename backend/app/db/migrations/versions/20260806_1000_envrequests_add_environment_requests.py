"""environment requests + environment handover fields

Revision ID: envrequests
Revises: usergroups
Create Date: 2026-08-06 10:00:00.000000

Purely additive: one new table and six nullable columns. No backfill — an
environment with empty handover fields is a legitimate state, not a defect.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envrequests'
down_revision: Union[str, None] = 'usergroups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("lifecycle_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("needed_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("proposed_name", sa.String(length=200), nullable=True),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
        sa.Column("created_environment_id", sa.Integer(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["lifecycle_id"], ["lifecycle_template.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["environment_tier.id"]),
        sa.ForeignKeyConstraint(["operations_group_id"], ["user_group.id"]),
        sa.ForeignKeyConstraint(["created_environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_environment_request_id", "environment_request", ["id"])
    op.create_index("ix_environment_request_tenant_id", "environment_request", ["tenant_id"])
    op.create_index("ix_environment_request_lifecycle_id", "environment_request", ["lifecycle_id"])
    op.create_index("ix_environment_request_requested_by", "environment_request", ["requested_by"])
    op.create_index("ix_environment_request_environment_id", "environment_request", ["environment_id"])
    op.create_index(
        "ix_environment_request_operations_group_id", "environment_request",
        ["operations_group_id"],
    )
    op.create_index(
        "ix_environment_request_created_environment_id", "environment_request",
        ["created_environment_id"],
    )

    for column, type_ in (
        ("access_url", sa.String(length=500)),
        ("connection_notes", sa.Text()),
        ("support_contact", sa.String(length=255)),
        ("sla_notes", sa.Text()),
        ("known_limitations", sa.Text()),
        ("decommission_notes", sa.Text()),
    ):
        op.add_column("environment", sa.Column(column, type_, nullable=True))


def downgrade() -> None:
    for column in (
        "decommission_notes", "known_limitations", "sla_notes",
        "support_contact", "connection_notes", "access_url",
    ):
        op.drop_column("environment", column)

    for index in (
        "ix_environment_request_created_environment_id",
        "ix_environment_request_operations_group_id",
        "ix_environment_request_environment_id",
        "ix_environment_request_requested_by",
        "ix_environment_request_lifecycle_id",
        "ix_environment_request_tenant_id",
        "ix_environment_request_id",
    ):
        op.drop_index(index, table_name="environment_request")
    op.drop_table("environment_request")
