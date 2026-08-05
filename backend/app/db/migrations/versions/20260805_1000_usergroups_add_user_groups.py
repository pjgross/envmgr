"""user groups + environment operations group

Revision ID: usergroups
Revises: envgovernance
Create Date: 2026-08-05 10:00:00.000000

Purely additive: two new tables and one nullable column. No backfill — an
environment with no operating team is a legitimate state that
`?governance_gap=` reports, not a defect to be papered over with a fabricated
group.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'usergroups'
down_revision: Union[str, None] = 'envgovernance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_group_tenant_id", "user_group", ["tenant_id"])
    # Base declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here, a migration-built database
    # differs from a create_all-built one — not caught by
    # test_migration_schema_drift.py, which compares only tables and columns.
    op.create_index("ix_user_group_id", "user_group", ["id"])

    op.create_table(
        "user_group_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["user_group.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_user_group_member"),
    )
    op.create_index("ix_user_group_member_tenant_id", "user_group_member", ["tenant_id"])
    op.create_index("ix_user_group_member_group_id", "user_group_member", ["group_id"])
    op.create_index("ix_user_group_member_user_id", "user_group_member", ["user_id"])
    # Base declares `id` with index=True — same reasoning as ix_user_group_id
    # above.
    op.create_index("ix_user_group_member_id", "user_group_member", ["id"])

    op.add_column(
        "environment",
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_environment_operations_group",
        "environment", "user_group",
        ["operations_group_id"], ["id"],
    )
    # Matches the name SQLAlchemy's default `ix_<table>_<column>` convention
    # gives this `index=True` column (compare `ix_environment_owner_user_id`
    # for the sibling `owner_user_id` column) — not shortened, unlike
    # `ix_environment_tier_fk`, because there is no name collision to dodge
    # here (see environment.py's __table_args__ comment for the one case
    # where there is).
    op.create_index(
        "ix_environment_operations_group_id", "environment", ["operations_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_environment_operations_group_id", table_name="environment")
    op.drop_constraint("fk_environment_operations_group", "environment", type_="foreignkey")
    op.drop_column("environment", "operations_group_id")

    op.drop_index("ix_user_group_member_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_user_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_group_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_tenant_id", table_name="user_group_member")
    op.drop_table("user_group_member")

    op.drop_index("ix_user_group_id", table_name="user_group")
    op.drop_index("ix_user_group_tenant_id", table_name="user_group")
    op.drop_table("user_group")
