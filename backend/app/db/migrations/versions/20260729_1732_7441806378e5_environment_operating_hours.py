"""environment operating hours

Revision ID: 7441806378e5
Revises: 4c95edc360c4
Create Date: 2026-07-29 17:32:44.188610

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7441806378e5'
down_revision: Union[str, None] = '4c95edc360c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_operating_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("week", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("environment_id", name="uq_env_operating_hours_env"),
    )
    op.create_index("ix_env_ophours_tenant_id", "environment_operating_hours", ["tenant_id"])
    op.create_index("ix_env_ophours_environment_id", "environment_operating_hours", ["environment_id"])


def downgrade() -> None:
    op.drop_table("environment_operating_hours")
