"""add_booking_custom_fields

Revision ID: 78916e9c70e8
Revises: b303ad51d0be
Create Date: 2026-03-23 18:12:49.327937

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78916e9c70e8'
down_revision: Union[str, None] = 'b303ad51d0be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("booking", sa.Column("custom_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("booking", "custom_fields")
