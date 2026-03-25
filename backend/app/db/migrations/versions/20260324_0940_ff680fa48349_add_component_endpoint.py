"""add_component_endpoint

Revision ID: ff680fa48349
Revises: 629381d81e87
Create Date: 2026-03-24 09:40:58.365804

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff680fa48349'
down_revision: Union[str, None] = '629381d81e87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_endpoint",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dependency_id", sa.Integer(), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dependency_id"], ["component_dependency.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_component_endpoint_dependency_id",
        "component_endpoint",
        ["dependency_id"],
    )
    op.create_index(
        "ix_component_endpoint_tenant_id",
        "component_endpoint",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_component_endpoint_tenant_id", table_name="component_endpoint")
    op.drop_index("ix_component_endpoint_dependency_id", table_name="component_endpoint")
    op.drop_table("component_endpoint")
