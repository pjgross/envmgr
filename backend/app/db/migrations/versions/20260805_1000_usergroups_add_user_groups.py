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
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_group_tenant_id", "user_group", ["tenant_id"])

    op.create_table(
        "user_group_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
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

    op.add_column(
        "environment",
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_environment_operations_group",
        "environment", "user_group",
        ["operations_group_id"], ["id"],
    )
    op.create_index(
        "ix_environment_operations_group", "environment", ["operations_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_environment_operations_group", table_name="environment")
    op.drop_constraint("fk_environment_operations_group", "environment", type_="foreignkey")
    op.drop_column("environment", "operations_group_id")

    op.drop_index("ix_user_group_member_user_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_group_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_tenant_id", table_name="user_group_member")
    op.drop_table("user_group_member")

    op.drop_index("ix_user_group_tenant_id", table_name="user_group")
    op.drop_table("user_group")
