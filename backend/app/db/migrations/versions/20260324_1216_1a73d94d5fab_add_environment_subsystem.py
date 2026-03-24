"""add_environment_subsystem

Revision ID: 1a73d94d5fab
Revises: ff680fa48349
Create Date: 2026-03-24 12:16:52.880860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a73d94d5fab'
down_revision: Union[str, None] = 'ff680fa48349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_subsystem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("subsystem_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("is_mocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mock_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["subsystem_id"], ["subsystem.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "subsystem_id", name="uq_env_subsystem"),
    )
    op.create_index("ix_environment_subsystem_environment_id", "environment_subsystem", ["environment_id"])
    op.create_index("ix_environment_subsystem_subsystem_id", "environment_subsystem", ["subsystem_id"])
    op.create_index("ix_environment_subsystem_tenant_id", "environment_subsystem", ["tenant_id"])

    op.drop_column("environment_system", "status")
    op.drop_column("environment_system", "mock_notes")


def downgrade() -> None:
    op.add_column("environment_system", sa.Column("mock_notes", sa.Text(), nullable=True))
    op.add_column("environment_system", sa.Column(
        "status", sa.VARCHAR(length=50), nullable=False, server_default="active"
    ))
    op.drop_index("ix_environment_subsystem_tenant_id", table_name="environment_subsystem")
    op.drop_index("ix_environment_subsystem_subsystem_id", table_name="environment_subsystem")
    op.drop_index("ix_environment_subsystem_environment_id", table_name="environment_subsystem")
    op.drop_table("environment_subsystem")
