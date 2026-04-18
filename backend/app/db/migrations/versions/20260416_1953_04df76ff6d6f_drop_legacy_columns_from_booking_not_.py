"""drop legacy columns from booking; NOT NULL on booking_request_id

Revision ID: 04df76ff6d6f
Revises: e1ae17b4bf4d
Create Date: 2026-04-16 19:53:33.531019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04df76ff6d6f'
down_revision: Union[str, None] = 'e1ae17b4bf4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("booking", "booking_request_id", nullable=False)
    op.drop_column("booking", "project_name")
    op.drop_column("booking", "booking_type_id")
    op.drop_column("booking", "notes")
    op.drop_column("booking", "exclusive_use")
    op.drop_column("booking", "context_tag")
    op.drop_column("booking", "custom_fields")
    op.drop_column("booking", "booked_by")


def downgrade() -> None:
    op.add_column("booking", sa.Column("booked_by", sa.Integer, sa.ForeignKey("user.id"), nullable=True))
    op.add_column("booking", sa.Column("custom_fields", sa.JSON, nullable=True))
    op.add_column("booking", sa.Column("context_tag", sa.String(50), nullable=False, server_default="none"))
    op.add_column("booking", sa.Column("exclusive_use", sa.Boolean, nullable=False, server_default=sa.text("false")))
    op.add_column("booking", sa.Column("notes", sa.Text, nullable=True))
    op.add_column("booking", sa.Column("booking_type_id", sa.Integer, sa.ForeignKey("booking_type.id"), nullable=True))
    op.add_column("booking", sa.Column("project_name", sa.String(200), nullable=True))
    op.alter_column("booking", "booking_request_id", nullable=True)
