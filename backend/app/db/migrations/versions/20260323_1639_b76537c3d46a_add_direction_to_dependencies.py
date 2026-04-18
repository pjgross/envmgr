"""add_direction_to_dependencies

Revision ID: b76537c3d46a
Revises: cedd5a0a1194
Create Date: 2026-03-23 16:39:45.748425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b76537c3d46a'
down_revision: Union[str, None] = 'cedd5a0a1194'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_dependency",
        sa.Column("direction", sa.String(10), nullable=False, server_default="one_way"),
    )
    op.add_column(
        "component_dependency",
        sa.Column("direction", sa.String(10), nullable=False, server_default="one_way"),
    )


def downgrade() -> None:
    op.drop_column("system_dependency", "direction")
    op.drop_column("component_dependency", "direction")
