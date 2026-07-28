"""environment health status

Revision ID: 22e121a21cd6
Revises: 02355a0014b8
Create Date: 2026-07-28 20:01:41.659576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22e121a21cd6'
down_revision: Union[str, None] = '02355a0014b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_health_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_env_health_tenant_id", "environment_health_status", ["tenant_id"])
    op.create_index("ix_env_health_environment_id", "environment_health_status", ["environment_id"])
    op.create_index("ix_env_health_tenant_env_recorded", "environment_health_status",
                    ["tenant_id", "environment_id", "recorded_at"])


def downgrade() -> None:
    op.drop_table("environment_health_status")
