"""projects, usage agreements, and the booking/release links

Revision ID: projects
Revises: envrequests
Create Date: 2026-08-07 10:00:00.000000

Purely additive: two new tables and two nullable columns. No backfill —
booking_request.project_name is deliberately kept, so there is nothing to
migrate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'projects'
down_revision: Union[str, None] = 'envrequests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("team_group_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["team_group_id"], ["user_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id. The
    # usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_project_id", "project", ["id"])
    op.create_index("ix_project_tenant_id", "project", ["tenant_id"])
    op.create_index("ix_project_team_group_id", "project", ["team_group_id"])

    op.create_table(
        "usage_agreement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_agreement_id", "usage_agreement", ["id"])
    op.create_index("ix_usage_agreement_tenant_id", "usage_agreement", ["tenant_id"])
    op.create_index("ix_usage_agreement_project_id", "usage_agreement", ["project_id"])
    op.create_index(
        "ix_usage_agreement_environment_id", "usage_agreement", ["environment_id"]
    )

    op.add_column("booking_request", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_booking_request_project", "booking_request", "project", ["project_id"], ["id"]
    )
    op.create_index("ix_booking_request_project_id", "booking_request", ["project_id"])

    op.add_column("release", sa.Column("owning_project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_release_owning_project", "release", "project", ["owning_project_id"], ["id"]
    )
    op.create_index("ix_release_owning_project_id", "release", ["owning_project_id"])


def downgrade() -> None:
    op.drop_index("ix_release_owning_project_id", table_name="release")
    op.drop_constraint("fk_release_owning_project", "release", type_="foreignkey")
    op.drop_column("release", "owning_project_id")

    op.drop_index("ix_booking_request_project_id", table_name="booking_request")
    op.drop_constraint("fk_booking_request_project", "booking_request", type_="foreignkey")
    op.drop_column("booking_request", "project_id")

    for index in (
        "ix_usage_agreement_environment_id",
        "ix_usage_agreement_project_id",
        "ix_usage_agreement_tenant_id",
        "ix_usage_agreement_id",
    ):
        op.drop_index(index, table_name="usage_agreement")
    op.drop_table("usage_agreement")

    for index in ("ix_project_team_group_id", "ix_project_tenant_id", "ix_project_id"):
        op.drop_index(index, table_name="project")
    op.drop_table("project")
