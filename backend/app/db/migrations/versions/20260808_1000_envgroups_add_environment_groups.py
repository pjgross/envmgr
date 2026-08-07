"""environment groups, membership, and the FK booking has lacked since March

Revision ID: envgroups
Revises: projects
Create Date: 2026-08-08 10:00:00.000000

Additive. Two new tables, plus a foreign key and index on
booking.environment_group_id — a column that has existed since
20260323_1413_0d99256c6a56_add_booking.py with no FK and no table to point at.
Every value in it is NULL and no code path has ever written it, so the
constraint cannot fail on existing data. No column is added and no backfill
is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envgroups'
down_revision: Union[str, None] = 'projects'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_environment_group_id", "environment_group", ["id"])
    op.create_index(
        "ix_environment_group_tenant_id", "environment_group", ["tenant_id"]
    )

    op.create_table(
        "environment_group_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["group_id"], ["environment_group.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_environment_group_member_id", "environment_group_member", ["id"]
    )
    op.create_index(
        "ix_environment_group_member_tenant_id",
        "environment_group_member", ["tenant_id"],
    )
    op.create_index(
        "ix_environment_group_member_group_id",
        "environment_group_member", ["group_id"],
    )
    op.create_index(
        "ix_environment_group_member_environment_id",
        "environment_group_member", ["environment_id"],
    )

    # The column already exists, unconstrained, since the March booking
    # migration — nothing has ever stopped a value being written to it that
    # doesn't (or no longer does) name a real environment_group row. That
    # includes a downgrade of this very revision: downgrade correctly leaves
    # the column and its values in place while dropping the table they
    # pointed at, so a down-then-up cycle on a database with group-linked
    # bookings would otherwise leave an orphan here too. Null any orphan
    # before adding the constraint, or upgrade fails and the next `upgrade
    # head` can never succeed. Cheap and a no-op on a clean deploy, where the
    # column is still all NULL.
    op.execute(
        "UPDATE booking SET environment_group_id = NULL "
        "WHERE environment_group_id IS NOT NULL "
        "AND NOT EXISTS ("
        "SELECT 1 FROM environment_group "
        "WHERE environment_group.id = booking.environment_group_id"
        ")"
    )
    op.create_foreign_key(
        "fk_booking_environment_group",
        "booking", "environment_group", ["environment_group_id"], ["id"],
    )
    op.create_index(
        "ix_booking_environment_group_id", "booking", ["environment_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_booking_environment_group_id", table_name="booking")
    op.drop_constraint(
        "fk_booking_environment_group", "booking", type_="foreignkey"
    )
    # The COLUMN stays — it predates this revision and downgrade must not
    # destroy it.

    for index in (
        "ix_environment_group_member_environment_id",
        "ix_environment_group_member_group_id",
        "ix_environment_group_member_tenant_id",
        "ix_environment_group_member_id",
    ):
        op.drop_index(index, table_name="environment_group_member")
    op.drop_table("environment_group_member")

    for index in ("ix_environment_group_tenant_id", "ix_environment_group_id"):
        op.drop_index(index, table_name="environment_group")
    op.drop_table("environment_group")
