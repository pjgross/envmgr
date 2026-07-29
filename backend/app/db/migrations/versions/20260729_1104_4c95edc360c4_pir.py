"""pir

Revision ID: 4c95edc360c4
Revises: 22e121a21cd6
Create Date: 2026-07-29 11:04:50.471978

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c95edc360c4'
down_revision: Union[str, None] = '22e121a21cd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pir",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id"), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("what_went_well", sa.Text(), nullable=True),
        sa.Column("what_went_wrong", sa.Text(), nullable=True),
        sa.Column("action_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pir_tenant_id", "pir", ["tenant_id"])
    op.create_index("ix_pir_release_id", "pir", ["release_id"])
    op.create_index("ix_pir_incident_id", "pir", ["incident_id"])
    op.create_index("ix_pir_tenant_release", "pir", ["tenant_id", "release_id"])
    op.create_index("ix_pir_tenant_incident", "pir", ["tenant_id", "incident_id"])


def downgrade() -> None:
    op.drop_table("pir")
